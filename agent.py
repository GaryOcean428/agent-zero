#!/usr/bin/env python3
"""Gary-Zero - Core agent implementation.

This module contains the core Agent class and related utilities for building
intelligent agents with support for tools, memory, and conversation management.
"""

# Standard library imports
import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import (
    Any,
    Dict,
    List,
    Optional,
    TypeVar,
    Callable,
    Deque,
    Coroutine,
)

# Third-party imports
import nest_asyncio
# type: ignore
# pylint: disable=import-error

# Local imports
try:
    from agent_zero.log import Log  # type: ignore
except ImportError:
    from python.helpers.log import Log

try:
    from agent_zero.dirty_json import DirtyJson  # type: ignore
except ImportError:
    from python.helpers.dirty_json import DirtyJson

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()


# Type definitions
@dataclass
class LoopData:
    """Container for loop-related data."""
    data: Dict[str, Any] = field(default_factory=dict)


class DeferredTask:
    """A task that can be started and managed asynchronously."""

    def __init__(self, thread_name: str):
        self.thread_name = thread_name
        self._task = None
        self._running = False

    def start_task(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> asyncio.Task[Any]:
        """Start the task with the given function and arguments."""
        if func is not None:
            task = asyncio.create_task(func(*args, **kwargs))
            self._task = task  # type: ignore
            self._running = True
            return task
        else:
            self._task = None
            self._running = False
            return asyncio.create_task(asyncio.sleep(0))

    def kill(self):
        """Cancel the task if it's running."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._running = False

    def is_alive(self) -> bool:
        """Check if the task is still running."""
        return self._running and self._task is not None and not self._task.done()


class Localization:
    """Handles localization and formatting of dates and times."""

    _instance: Optional["Localization"] = None

    @classmethod
    def get(cls) -> "Localization":
        """Get the singleton instance of Localization."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def serialize_datetime(self, dt: datetime) -> str:
        """Convert datetime to ISO format string."""
        return dt.isoformat() if dt else ""


# Type aliases
T = TypeVar("T")
R = TypeVar("R")
JsonType = Dict[str, Any]

# Constants
DEFAULT_PROMPT_DIR = "prompts/default"


class ModelProvider(Enum):
    """Enum for supported model providers."""

    OPENAI = auto()
    ANTHROPIC = auto()
    LOCAL = auto()


class AgentContextType(str, Enum):
    """Types of agent contexts."""

    USER = "user"
    TASK = "task"
    MCP = "mcp"


class AgentContext:
    _contexts: dict[str, "AgentContext"] = {}
    _counter: int = 0

    def __init__(
        self,
        config: "AgentConfig",
        context_id: Optional[str] = None,
        context_name: Optional[str] = None,
        agent0: Optional["Agent"] = None,
        log: Optional[Log.Log] = None,
        paused: bool = False,
        streaming_agent: Optional["Agent"] = None,
        created_at: Optional[datetime] = None,
        context_type: AgentContextType = AgentContextType.USER,
        last_message: Optional[datetime] = None,
    ):
        # build context
        self.id = context_id or str(uuid.uuid4())
        self.name = context_name
        self.config = config
        self.log = log or Log.Log()
        self.agent0 = agent0 or Agent(0, self.config, self)
        self.paused = paused
        self.streaming_agent = streaming_agent
        self.task: DeferredTask | None = None
        self.created_at = created_at or datetime.now(timezone.utc)
        self.type = context_type
        AgentContext._counter += 1
        self.no = AgentContext._counter
        # set to start of unix epoch
        self.last_message = last_message or datetime.now(timezone.utc)

        existing = self._contexts.get(self.id, None)
        if existing:
            AgentContext.remove(self.id)
        self._contexts[self.id] = self

    @staticmethod
    def get(context_id: str) -> Optional["AgentContext"]:
        return AgentContext._contexts.get(context_id, None)

    @staticmethod
    def first():
        if not AgentContext._contexts:
            return None
        return list(AgentContext._contexts.values())[0]

    @staticmethod
    def all():
        return list(AgentContext._contexts.values())

    @staticmethod
    def remove(context_id: str) -> Optional["AgentContext"]:
        context = AgentContext._contexts.pop(context_id, None)
        if context and context.task:
            context.task.kill()
        return context

    def serialize(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": (
                Localization.get().serialize_datetime(self.created_at)
                if self.created_at
                else Localization.get().serialize_datetime(datetime.fromtimestamp(0))
            ),
            "no": self.no,
            "log_guid": self.log.guid,
            "log_version": len(self.log.updates),
            "log_length": len(self.log.logs),
            "paused": self.paused,
            "last_message": (
                Localization.get().serialize_datetime(self.last_message)
                if self.last_message
                else Localization.get().serialize_datetime(datetime.fromtimestamp(0))
            ),
            "type": self.type.value,
        }

    @staticmethod
    def log_to_all(
        log_type: Log.Type,
        heading: Optional[str] = None,
        content: Optional[str] = None,
        kvps: Optional[Dict[str, Any]] = None,
        temp: Optional[bool] = None,
        update_progress: Optional[Log.ProgressUpdate] = None,
        log_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Log.LogItem]:
        items: List[Log.LogItem] = []
        for context in AgentContext.all():
            items.append(
                context.log.log(
                    log_type,
                    heading,
                    content,
                    kvps,
                    temp,
                    update_progress,
                    log_id,
                    **kwargs,
                )
            )
        return items

    def kill_process(self):
        if self.task:
            self.task.kill()

    def reset(self):
        self.kill_process()
        self.log.reset()
        self.agent0 = Agent(0, self.config, self)
        self.streaming_agent = None
        self.paused = False

    def nudge(self):
        self.kill_process()
        self.paused = False
        self.task = self.run_task(self.get_agent().monologue)
        return self.task

    def get_agent(self):
        return self.streaming_agent or self.agent0

    def communicate(self, msg: "UserMessage", broadcast_level: int = 1):
        self.paused = False  # unpause if paused

        current_agent = self.get_agent()

        if self.task and self.task.is_alive():
            # set intervention messages to agent(s):
            intervention_agent = current_agent
            while intervention_agent and broadcast_level != 0:
                intervention_agent.intervention = msg
                broadcast_level -= 1
                intervention_agent = intervention_agent.data.get(
                    Agent.DATA_NAME_SUPERIOR, None
                )
        else:
            self.task = self.run_task(self._process_chain, current_agent, msg)

        return self.task

    def run_task(
        self, func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any
    ):
        if not self.task:
            self.task = DeferredTask(
                thread_name=self.__class__.__name__,
            )
        self.task.start_task(func, *args, **kwargs)
        return self.task

    # this wrapper ensures that superior agents are called back if the chat was loaded from file and original callstack is gone
    async def _process_chain(
        self, agent: "Agent", msg: "UserMessage|str", user: bool = True
    ) -> Any:
        """Process a message through the agent chain.

        Args:
            agent: The agent to process the message
            msg: The message to process
            user: Whether this is a user message

        Returns:
            The response from the agent chain

        Raises:
            Exception: If there's an error processing the message
        """
        try:
            # Add message to history if it's a user message
            if user and isinstance(msg, UserMessage):
                agent.memory.append(msg)
            elif not user and isinstance(msg, str):
                agent.memory.append(AgentMessage(msg))

            if hasattr(agent, "monologue") and callable(getattr(agent, "monologue")):
                response = await agent.monologue()
            else:
                response = msg
            superior = agent.data.get(Agent.DATA_NAME_SUPERIOR, None)
            if superior:
                response = await self._process_chain(superior, response, False)
            return response
        except Exception as e:  # pylint: disable=broad-except
            if hasattr(agent, "handle_critical_exception"):
                agent.handle_critical_exception(e)
            else:
                getattr(self, "logger", logging).error(
                    "Error in process chain: %s", str(e), exc_info=True
                )
                raise

    def concat_messages(
        self,
        start_idx: int = 0,
        end_idx: Optional[int] = None,
        topic: Optional[str] = None,
    ) -> str:
        """Concatenate message texts with optional filtering.

        Args:
            start_idx: Starting message index (inclusive)
            end_idx: Ending message index (exclusive). If None, goes to end of history.
            topic: Optional topic to filter messages by

        Returns:
            str: Concatenated message texts as a single string

        Example:
            # Get all messages
            all_msgs = agent.concat_messages()

            # Get last 5 messages
            recent_msgs = agent.concat_messages(start_idx=-5)

            # Get messages about a specific topic
            topic_msgs = agent.concat_messages(topic="system")
        """
        history = getattr(self, "memory", [])
        if not history:
            return ""

        # Handle negative indices
        if start_idx < 0:
            start_idx = max(0, len(history) + start_idx)
        if end_idx is not None and end_idx < 0:
            end_idx = len(history) + end_idx

        messages = history[start_idx : end_idx if end_idx is not None else len(history)]
        if topic:
            messages = [
                msg
                for msg in messages
                if hasattr(msg, "topic") and getattr(msg, "topic", None) == topic
            ]

        return "\n".join(getattr(msg, "content", "") for msg in messages)


class Message(ABC):
    """Abstract base class for messages in the agent system."""

    def __init__(self, content: str) -> None:
        """Initialize the message with content.

        Args:
            content: The message content
        """
        self.content = content
        self.timestamp = datetime.now(timezone.utc)

    @abstractmethod
    def summarize(self) -> str:
        """Return a string summary of the message.

        Returns:
            str: A string representation of the message
        """
        raise NotImplementedError("Subclasses must implement summarize()")


class UserMessage(Message):
    """A message from the user to the agent."""

    def __init__(self, content: str, user_id: Optional[str] = None) -> None:
        """Initialize a user message.

        Args:
            content: The message content
            user_id: Optional user ID
        """
        super().__init__(content)
        self.user_id = user_id

    def summarize(self) -> str:
        """Return a summary of the user message.

        Returns:
            str: A summary of the user message
        """
        return f"User ({self.user_id or 'anonymous'}): {self.content[:100]}"


class AgentMessage(Message):
    """A message from the agent to the user."""

    def __init__(self, content: str) -> None:
        """Initialize an agent message.

        Args:
            content: The message content
        """
        super().__init__(content)

    def summarize(self) -> str:
        """Return a summary of the agent message.

        Returns:
            str: A summary of the agent message
        """
        return f"Agent: {self.content[:100]}"

    def get_user_input(self, prompt: str = "") -> str:
        """Get input from the user.

        Args:
            prompt: The prompt to display to the user

        Returns:
            str: The user's input

        Raises:
            NotImplementedError: If the method is not implemented by a subclass
        """
        raise NotImplementedError("Subclasses must implement get_user_input()")


@dataclass
class AgentConfig:
    """Configuration for an Agent instance.

    Attributes:
        name: The name of the agent
        model_provider: The model provider to use
        model_name: The name of the model to use
        temperature: Temperature for model sampling
        max_tokens: Maximum number of tokens to generate
        system_prompt: The system prompt to use
        tools: List of tool names to enable
        memory_size: Maximum number of messages to keep in memory
    """

    name: str = "Agent"
    model_provider: ModelProvider = ModelProvider.OPENAI
    model_name: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 2000
    system_prompt: str = "You are a helpful AI assistant."
    tools: List[str] = field(default_factory=list)
    memory_size: int = 10


class Agent:
    """Main agent class that handles the core agent functionality.

    This class provides the main interface for interacting with the agent,
    including sending messages, processing responses, and managing state.
    """

    # Class constants for data storage keys
    DATA_NAME_SUPERIOR = "_superior"
    DATA_NAME_SUBORDINATE = "_subordinate"
    DATA_NAME_CTX_WINDOW = "ctx_window"

    def __init__(
        self, _: int, config: "AgentConfig", context: Optional["AgentContext"] = None
    ) -> None:
        """Initialize the agent with configuration.

        Args:
            _: Unused parameter for compatibility
            config: Configuration for the agent
            context: Optional context for the agent

        Raises:
            ValueError: If config is not provided or is invalid
        """
        if not config:
            raise ValueError("Agent config is required")

        self.config = config
        self.context = context
        self.name = getattr(config, "name", "Agent")
        self.id = str(uuid.uuid4())
        self.logger = logging.getLogger(f"agent.{self.name}")
        self.memory: Deque[Message] = deque(maxlen=getattr(config, "memory_size", 10))
        self._tools: Dict[str, Callable[..., Any]] = {}
        self._loop_data: Optional[LoopData] = None
        self._last_message: Optional[Message] = None
        self._system_prompt: Optional[str] = None
        self.last_activity = datetime.now(timezone.utc)
        self.intervention: Optional[UserMessage] = None
        self.data: Dict[str, Any] = {}
        self._load_tools()

        self.logger.info("Initialized agent %s (ID: %s)", self.name, self.id[:8])

    def _load_tools(self) -> None:
        """Load the tools specified in the config."""
        for tool_name in self.config.tools:
            try:
                tool = self.get_tool(tool_name)
                if tool:
                    self._tools[tool_name] = tool
                    self.logger.info("Loaded tool: %s", tool_name)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error("Failed to load tool %s: %s", tool_name, str(e))

    async def get_system_prompt(self, loop_data: "LoopData") -> List[str]:
        """Generate the system prompt for the agent.

        This method constructs the system prompt by combining the base prompt
        from the configuration with any extensions that might modify it.

        Args:
            loop_data: Current loop data containing state information

        Returns:
            List[str]: The complete system prompt as a list of strings

        Raises:
            RuntimeError: If there's an error generating the system prompt
            ValueError: If the agent configuration is invalid
        """
        if not hasattr(self, "config") or not hasattr(self.config, "system_prompt"):
            raise ValueError("Agent configuration is missing required 'system_prompt'")

        try:
            prompt_parts: List[str] = [
                f"You are {getattr(self.config, 'name', 'an AI assistant')}.",
                self.config.system_prompt,
            ]

            # Add tool descriptions if tools are available
            if hasattr(self, "_tools") and self._tools:
                prompt_parts.append("\nYou have access to the following tools:")
                for tool_name, tool in self._tools.items():
                    doc = getattr(tool, "__doc__", "No description available.")
                    prompt_parts.append(f"- {tool_name}: {doc}")

            # Allow extensions to modify the system prompt if loop is running
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    # Check for a method to get extended system prompt
                    if hasattr(self, "_get_extended_system_prompt") and callable(
                        getattr(self, "_get_extended_system_prompt", None)
                    ):
                        try:
                            extended_prompt = await getattr(
                                self, "_get_extended_system_prompt"
                            )(loop_data)
                            if extended_prompt and isinstance(extended_prompt, list):
                                prompt_parts.extend(extended_prompt)
                        except Exception as e:  # pylint: disable=broad-except
                            self.logger.warning(
                                "Failed to get extended system prompt: %s",
                                str(e),
                                exc_info=self.logger.isEnabledFor(logging.DEBUG),
                            )
            except RuntimeError:
                # No running event loop, continue without extensions
                pass

            return prompt_parts

        except asyncio.CancelledError:
            self.logger.debug("System prompt generation was cancelled")
            raise
        except Exception as e:
            self.logger.error(
                "Error generating system prompt: %s",
                str(e),
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            raise RuntimeError(f"Failed to generate system prompt: {str(e)}") from e

    def log_from_stream(self, stream: str, log_item: Any) -> None:
        """Log messages from a stream.

        Args:
            stream: The stream to log from
            log_item: The log item to process

        Raises:
            RuntimeError: If there's an error processing the stream
        """
        try:
            # First try to parse as JSON
            try:
                response = DirtyJson.parse_string(stream)
                if isinstance(response, dict):
                    if "content" in response and response["content"]:
                        log_item.log(str(response["content"]), Log.LogLevel.INFO)
                    if "error" in response and response["error"]:
                        log_item.log(f"Error: {response['error']}", Log.LogLevel.ERROR)
                    return
            except (ValueError, TypeError):
                # Not valid JSON, continue with raw stream processing
                pass

            # Process raw stream
            logging.debug("Processing stream: %s", stream)

            # Example of using the imported modules
            if hasattr(Log, "LogItem"):
                log_item = Log.LogItem(level=Log.LogLevel.INFO, message=stream)
                Log.log(log_item)

        except (IOError, ValueError) as e:
            error_msg = f"Error processing stream: {str(e)}"
            logging.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e
        except Exception as e:  # pylint: disable=broad-except
            logging.exception("Unexpected error processing stream content")
            raise RuntimeError(f"Failed to process stream: {str(e)}") from e

    @property
    def loop_data(self) -> Optional["LoopData"]:
        """Get the current loop data for the agent.

        Returns:
            Optional[LoopData]: The current loop data if set, None otherwise.

        Note:
            Loop data contains state information for the current processing
            loop of the agent, which can be used to maintain context between
            different processing cycles.
        """
        return self._loop_data

    @loop_data.setter
    def loop_data(self, value: Optional["LoopData"]) -> None:
        """Set the loop data for the agent.

        Args:
            value: The LoopData to set, or None to clear the current data.

        Note:
            This updates the agent's internal loop state, which can be used
            to maintain context between different processing cycles.
        """
        self._loop_data = value

        # Log loop data updates if debug logging is enabled
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "Updated loop_data: %s", "Set" if value is not None else "Cleared"
            )

    @property
    def last_message(self) -> Optional[Message]:
        """Get the last message received by the agent.

        Returns:
            Optional[Message]: The last message received by the agent,
                            or None if no messages have been received.

        Note:
            This property tracks the most recent message processed by the agent,
            which can be used to maintain conversation context.
        """
        return self._last_message

    @last_message.setter
    def last_message(self, value: Optional[Message]) -> None:
        """Set the last message and update last activity time.

        Args:
            value: The message to set as the last message.
                  Can be None to clear the last message.

        Note:
            Updating this property also updates the agent's last_activity timestamp.
            This is useful for tracking agent idle time and session management.
        """
        self._last_message = value
        self.last_activity = datetime.now(timezone.utc)

        # Log message updates if debug logging is enabled
        if self.logger.isEnabledFor(logging.DEBUG) and value:
            msg_type = value.__class__.__name__
            self.logger.debug(
                "Updated last_message to %s (type: %s, length: %d)",
                value.summarize() if hasattr(value, "summarize") else "[no summary]",
                msg_type,
                len(getattr(value, "content", "")),
            )

    def _validate_tool_name(self, name: str) -> None:
        """Validate tool name input.
        
        Args:
            name: Tool name to validate
            
        Raises:
            ValueError: If name is invalid
        """
        if not name or not isinstance(name, str) or not name.isidentifier():
            raise ValueError("Tool name must be a non-empty string and valid Python identifier")

    def _get_cached_tool(self, name: str) -> Optional[Callable[..., Any]]:
        """Get tool from cache if available.
        
        Args:
            name: Tool name
            
        Returns:
            Optional[Callable]: Cached tool or None
        """
        if name in self._tools:
            self.logger.debug("Returning cached tool: %s", name)
            return self._tools[name]
        return None

    def _load_tool_from_module(self, name: str) -> Optional[Callable[..., Any]]:
        """Load tool from module directory.
        
        Args:
            name: Tool name
            
        Returns:
            Optional[Callable]: Loaded tool or None
        """
        try:
            tool_name = name.lower().replace('-', '_')
            module_name = f"agent_zero.tools.{tool_name}"
            
            tool_module = __import__(module_name, fromlist=["*"])
            tool_class_name = f"{''.join(x.title() for x in tool_name.split('_'))}Tool"
            tool_class = getattr(tool_module, tool_class_name, None)

            if tool_class and callable(tool_class):
                self.logger.info("Loading tool from module: %s", module_name)
                tool = tool_class()
                self._tools[name] = tool
                return tool
                
        except (ImportError, AttributeError) as e:
            self.logger.debug("Could not load tool %s from module: %s", name, str(e))
            
        return None

    def _get_builtin_tool(self, name: str) -> Optional[Callable[..., Any]]:
        """Get builtin tool if available.
        
        Args:
            name: Tool name
            
        Returns:
            Optional[Callable]: Builtin tool or None
        """
        builtin_tools: Dict[str, Callable[..., Any]] = {
            # Example built-in tools
            # 'search': SearchTool(),
            # 'calculator': CalculatorTool(),
        }

        if name in builtin_tools:
            self.logger.info("Using built-in tool: %s", name)
            tool = builtin_tools[name]
            self._tools[name] = tool
            return tool
            
        return None

    def get_tool(self, name: str) -> Optional[Callable[..., Any]]:
        """Get a tool by name.

        This method attempts to load a tool from multiple sources in the following order:
        1. Already loaded tools in memory
        2. Tools in the tools/ directory (as Python modules)
        3. Built-in tools

        Args:
            name: Name of the tool to get. Should be a valid Python identifier.

        Returns:
            Optional[Callable[..., Any]]: The requested tool or None if not found

        Raises:
            ValueError: If name is empty, None, or not a string
            RuntimeError: If there's an error loading the tool
        """
        try:
            self._validate_tool_name(name)
            
            # Check cache first
            cached_tool = self._get_cached_tool(name)
            if cached_tool:
                return cached_tool

            # Try loading from module
            module_tool = self._load_tool_from_module(name)
            if module_tool:
                return module_tool

            # Try builtin tools
            builtin_tool = self._get_builtin_tool(name)
            if builtin_tool:
                return builtin_tool

            self.logger.warning("Tool not found: %s", name)
            return None

        except ValueError:
            raise
        except Exception as e:
            error_msg = f"Error loading tool {name}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e

    async def call_extensions(self, folder: str, **kwargs: Any) -> Any:
        """Call all extensions in the specified folder.

        Args:
            folder: The folder containing the extensions to call
            **kwargs: Additional arguments to pass to the extensions

        Returns:
            Any: The result of the last extension called

        Raises:
            ImportError: If there's an error importing an extension
        """
        try:
            from python.helpers import extract_tools

            classes = extract_tools.load_classes_from_folder(
                f"python/extensions/{folder}", "*", object
            )
            for cls in classes:
                if hasattr(cls, "execute") and callable(getattr(cls, "execute")):
                    instance = cls()
                    await getattr(instance, "execute")(**kwargs)
        except ImportError as e:
            self.logger.error("Failed to import extensions: %s", str(e))
            raise
