from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from llm import LLMClient
from permissions import PermissionChecker
from session import SessionStore
from tools.base import Tool, ToolResult

_MAX_RETRIES = 3
_RETRY_BACKOFF = (1.0, 2.0)


class AbortedError(Exception):
    pass


class Engine:
    def __init__(
        self,
        tools: list[Tool],
        system_prompt: str,
        permission_checker: PermissionChecker,
        provider: str = "mock",
        model: str = "mock-sonnet",
        max_tokens: int = 1024,
        api_key: str | None = None,
        base_url: str | None = None,
        effort: str | None = None,
        session_store: SessionStore | None = None,
    ):
        self._tools = {tool.name: tool for tool in tools}
        self._system_prompt = system_prompt
        self._permissions = permission_checker
        self._client = LLMClient(provider=provider, api_key=api_key, base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort
        self._messages: list[dict[str, Any]] = []
        self._session_store = session_store
        self._aborted = False
        self._active_stream = None
        self._turn_start_len: int | None = None

    def _persist(self, message: dict[str, Any]) -> None:
        if self._session_store is not None:
            try:
                self._session_store.append_message(message)
            except Exception:
                pass

    def get_messages(self) -> list[dict]:
        return list(self._messages)

    def set_messages(self, messages: list[dict]) -> None:
        self._messages = list(messages)

    def set_tools(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def set_session_store(self, store: SessionStore | None) -> None:
        self._session_store = store

    def get_system_prompt(self) -> str:
        return self._system_prompt

    def abort(self) -> None:
        self._aborted = True
        if self._active_stream is not None:
            try:
                self._active_stream.close()
            except Exception:
                pass

    def cancel_turn(self) -> None:
        if self._turn_start_len is not None:
            del self._messages[self._turn_start_len:]
            self._turn_start_len = None

    def submit(self, user_input: str | list) -> Iterator[tuple]:
        self._aborted = False
        self._turn_start_len = len(self._messages)
        self._messages.append({"role": "user", "content": user_input})
        self._persist(self._messages[-1])

        try:
            while True:
                if self._aborted:
                    raise AbortedError()

                tool_uses = []
                final = None
                for attempt in range(_MAX_RETRIES): # 第2波新增功能，异常重试，回退message，重新请求
                    try:
                        with self._client.stream_messages(
                            model=self._model,
                            max_tokens=self._max_tokens,
                            system=self._system_prompt,
                            tools=[tool.to_api_schema() for tool in self._tools.values()],
                            messages=self._messages,
                            effort=self._effort,
                        ) as stream:
                            self._active_stream = stream
                            got_text = False
                            for text in stream.text_stream:
                                if self._aborted:
                                    raise AbortedError()
                                got_text = True
                                yield ("text", text) # 模型返回的文本，事件("text", text_chunk)
                            if got_text:
                                yield ("waiting",) # 带 yield 的函数：跑到 yield 就暂停，把值交出去；下次再从暂停点继续。

                            final = stream.get_final_message()
                            usage = getattr(final, "usage", None)
                            if usage is not None:
                                yield ("usage", usage)
                            for block in final.content:
                                if _block_type(block) == "tool_use":
                                    tool_uses.append(block)
                        break
                    except AbortedError:
                        raise
                    except Exception as exc:
                        if self._client.is_authentication_error(exc):
                            self._messages.pop()
                            yield ("error", f"Authentication failed: {self._client.error_message(exc)}")
                            return
                        if self._client.is_retryable_error(exc): # 异常重试，回退message，重新请求
                            if attempt < _MAX_RETRIES - 1:
                                wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                                yield ("error", f"API error, retrying in {wait:.0f}s... ({self._client.error_message(exc)})")
                                time.sleep(wait)
                                continue
                            self._messages.pop()
                            yield ("error", f"API error after {_MAX_RETRIES} retries: {self._client.error_message(exc)}")
                            return
                        if self._client.is_api_error(exc):
                            self._messages.pop()
                            yield ("error", f"API error: {self._client.error_message(exc)}")
                            return
                        raise
                    finally:
                        self._active_stream = None

                if final is None:
                    self._messages.pop()
                    return
                assistant_content = []
                for block in final.content:
                    if _block_type(block) == "text":
                        assistant_content.append({"type": "text", "text": _block_text(block)})
                    elif _block_type(block) == "tool_use":
                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": _block_id(block),
                                "name": _block_name(block),
                                "input": _block_input(block),
                            }
                        )
                self._messages.append({"role": "assistant", "content": assistant_content})
                self._persist(self._messages[-1])

                if not tool_uses:
                    break
               # 第2波新增功能，并发处理可读工具
                tool_results = []
                batches: list[tuple[bool, list[Any]]] = []
                for tu in tool_uses:
                    tool = self._tools.get(_block_name(tu))
                    is_concurrent = tool is not None and tool.is_read_only()
                    if batches and batches[-1][0] == is_concurrent and is_concurrent: #模型返回的 tool_uses 是按顺序罗列的。只有相邻的多个只读才可以安全地打成一包，用线程池一起跑；中间只要夹了一个非只读，batch 就被切断，必须先按段执行完再执行下一段，这样才符合「先写后读」这类隐含顺序
                        batches[-1][1].append(tu)
                    else:
                        batches.append((is_concurrent, [tu]))

                for is_concurrent, batch in batches:
                    if self._aborted:
                        raise AbortedError()
                    if is_concurrent and len(batch) > 1: # 并发处理可读工具
                        approved: list[tuple[Any, Tool]] = []
                        denied_results: dict[str, ToolResult] = {}

                        for tu in batch: #tu为tool_use， for tool_use in tool_uses:
                            name = _block_name(tu)
                            inputs = _block_input(tu)
                            tool = self._tools.get(name)
                            activity = tool.get_activity_description(**inputs) if tool else None
                            yield ("tool_call", name, inputs, activity)
                            if tool is None:
                                denied_results[_block_id(tu)] = ToolResult(content=f"Unknown tool: {name}", is_error=True)
                            elif self._permissions.check(tool, inputs) == "deny":
                                denied_results[_block_id(tu)] = ToolResult(content="Permission denied.", is_error=True)
                            else:
                                approved.append((tu, tool))
                                yield ("tool_executing", name, inputs, activity)

                        executed_results: dict[str, ToolResult] = {}
                        if approved:
                            with ThreadPoolExecutor(max_workers=min(len(approved), 8)) as pool:
                                future_map = {
                                    pool.submit(self._execute_tool, _block_name(tu), _block_input(tu)): tu
                                    for tu, _tool in approved
                                }
                                for future in as_completed(future_map):
                                    tu = future_map[future]
                                    try:
                                        executed_results[_block_id(tu)] = future.result()
                                    except Exception as exc:
                                        executed_results[_block_id(tu)] = ToolResult(
                                            content=f"Tool execution error: {exc}",
                                            is_error=True,
                                        )

                        for tu in batch:
                            tid = _block_id(tu) # 工具使用id
                            name = _block_name(tu)
                            inputs = _block_input(tu)
                            result = denied_results.get(tid) or executed_results.get(tid)
                            if result is None:
                                result = ToolResult(content="No result", is_error=True)
                            yield ("tool_result", name, inputs, result)
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tid,
                                    "content": result.content,
                                    "is_error": result.is_error,
                                }
                            )
                    else:
                        for tu in batch: # 顺序处理非可读工具
                            name = _block_name(tu)
                            inputs = _block_input(tu)
                            tool = self._tools.get(name)
                            activity = tool.get_activity_description(**inputs) if tool else None
                            yield ("tool_call", name, inputs, activity)

                            if tool is None:
                                result = ToolResult(content=f"Unknown tool: {name}", is_error=True)
                            elif self._permissions.check(tool, inputs) == "deny":
                                result = ToolResult(content="Permission denied.", is_error=True)
                            else:
                                yield ("tool_executing", name, inputs, activity)
                                result = self._execute_tool(name, inputs)

                            yield ("tool_result", name, inputs, result)
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": _block_id(tu),
                                    "content": result.content,
                                    "is_error": result.is_error,
                                }
                            )

                self._messages.append({"role": "user", "content": tool_results})
                self._persist(self._messages[-1])
        except AbortedError:
            self.cancel_turn()
            raise

    def _execute_tool(self, tool_name: str, inputs: dict) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)
        try:
            return tool.execute(**inputs)
        except Exception as exc:
            return ToolResult(content=f"Tool error: {exc}", is_error=True)


def _block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _block_name(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("name", ""))
    return str(getattr(block, "name", "") or "")


def _block_id(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("id", ""))
    return str(getattr(block, "id", "") or "")


def _block_text(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("text", ""))
    return str(getattr(block, "text", "") or "")


def _block_input(block: Any) -> dict:
    if isinstance(block, dict):
        raw = block.get("input", {})
    else:
        raw = getattr(block, "input", {})
    return raw if isinstance(raw, dict) else {}
