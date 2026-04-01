/**
 * Tests for codex.ts - Codex SDK integration.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { SessionState } from "./types.js";

type TestThreadItem = {
  type: string;
  [key: string]: unknown;
};

type TestThreadEvent = {
  type: string;
  [key: string]: unknown;
};

type TestThreadOptions = {
  skipGitRepoCheck?: boolean;
  model?: string;
  [key: string]: unknown;
};

vi.mock("./session.js", () => ({
  emit: vi.fn(),
  emitOutput: vi.fn(),
  emitMetadata: vi.fn(),
  emitError: vi.fn(),
  emitHeartbeat: vi.fn(),
  emitExit: vi.fn(),
  emitHeader: vi.fn(),
}));

vi.mock(
  "../../codex-src/sdk/typescript/src/index.js",
  () => ({
    Codex: vi.fn(() => ({
      startThread: vi.fn(),
      resumeThread: vi.fn(),
    })),
  }),
  { virtual: true }
);

import {
  emitOutput,
  emitMetadata,
  emitError,
  emitHeader,
} from "./session.js";

const loadCodexModule = () => import("./codex.js");

function createTestSession(): SessionState {
  return {
    id: "test-session",
    running: false,
    pendingInputs: [],
    subscribers: new Set(),
    eventBuffer: [],
  };
}

function createTestOptions(): TestThreadOptions {
  return { skipGitRepoCheck: true };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("formatStep", () => {
  it("formats reasoning item", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "reasoning",
      text: "Let me think about this...",
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("Let me think about this...");
  });

  it("formats command_execution item with exit code", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "command_execution",
      command: "npm test",
      exit_code: 0,
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("Command: npm test (exit 0)");
  });

  it("formats command_execution item without exit code", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "command_execution",
      command: "npm run build",
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("Command: npm run build");
  });

  it("formats file_change item", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "file_change",
      changes: [
        { path: "src/index.ts", action: "create" },
        { path: "src/utils.ts", action: "modify" },
      ],
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("File change: 2 file(s)");
  });

  it("formats file_change item with empty changes", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "file_change",
      changes: [],
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("File change: 0 file(s)");
  });

  it("formats mcp_tool_call item", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "mcp_tool_call",
      server: "filesystem",
      tool: "read_file",
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("MCP: filesystem.read_file");
  });

  it("formats web_search item", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "web_search",
      query: "how to fix npm install error",
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("Web search: how to fix npm install error");
  });

  it("formats todo_list item", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "todo_list",
      items: [
        { text: "Task 1", completed: true },
        { text: "Task 2", completed: false },
        { text: "Task 3", completed: false },
      ],
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("Todo list: 2 remaining");
  });

  it("formats error item", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "error",
      message: "Command failed with exit code 1",
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("Error: Command failed with exit code 1");
  });

  it("returns empty string for unknown types", async () => {
    const { formatStep } = await loadCodexModule();
    const item = {
      type: "unknown_type",
    } as TestThreadItem;

    expect(formatStep(item as never)).toBe("");
  });
});

describe("handleEvent", () => {
  describe("thread.started", () => {
    it("sets threadId and emits header", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "thread.started",
        thread_id: "thread-abc123",
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(session.threadId).toBe("thread-abc123");
      expect(emitHeader).toHaveBeenCalledWith(session, "Codex SDK Sidecar", {
        model: "default",
        provider: "OpenAI (Codex)",
        thread_id: "thread-abc123",
      });
    });

    it("uses model from options when set", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = { ...createTestOptions(), model: "gpt-4o" };

      const event = {
        type: "thread.started",
        thread_id: "thread-xyz",
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitHeader).toHaveBeenCalledWith(session, "Codex SDK Sidecar", {
        model: "gpt-4o",
        provider: "OpenAI (Codex)",
        thread_id: "thread-xyz",
      });
    });
  });

  describe("item.completed", () => {
    it("emits final output for agent_message", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "item.completed",
        item: {
          type: "agent_message",
          text: "Here is the result",
        },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitOutput).toHaveBeenCalledWith(session, "Here is the result\n", "final");
    });

    it("appends newline to agent_message if missing", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "item.completed",
        item: {
          type: "agent_message",
          text: "Response without newline",
        },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitOutput).toHaveBeenCalledWith(session, "Response without newline\n", "final");
    });

    it("does not double newline for agent_message", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "item.completed",
        item: {
          type: "agent_message",
          text: "Already has newline\n",
        },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitOutput).toHaveBeenCalledWith(session, "Already has newline\n", "final");
    });

    it("emits step output for other item types", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "item.completed",
        item: {
          type: "command_execution",
          command: "ls -la",
          exit_code: 0,
        },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitOutput).toHaveBeenCalledWith(session, "Command: ls -la (exit 0)\n", "step");
    });

    it("does not emit for items with empty formatStep", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "item.completed",
        item: {
          type: "unknown_type",
        },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitOutput).not.toHaveBeenCalled();
    });
  });

  describe("turn.completed", () => {
    it("emits usage metadata", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "turn.completed",
        usage: {
          input_tokens: 100,
          cached_input_tokens: 50,
          output_tokens: 200,
        },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitMetadata).toHaveBeenCalledWith(session, "input_tokens", 100, "100");
      expect(emitMetadata).toHaveBeenCalledWith(session, "cached_input_tokens", 50, "50");
      expect(emitMetadata).toHaveBeenCalledWith(session, "output_tokens", 200, "200");
      expect(emitMetadata).toHaveBeenCalledWith(session, "tokens_used", 350, "350");
    });

    it("calculates total tokens correctly", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "turn.completed",
        usage: {
          input_tokens: 1000,
          cached_input_tokens: 200,
          output_tokens: 500,
        },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitMetadata).toHaveBeenCalledWith(session, "tokens_used", 1700, "1700");
    });
  });

  describe("turn.failed", () => {
    it("emits error with message", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "turn.failed",
        error: { message: "Turn failed due to timeout" },
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitError).toHaveBeenCalledWith(
        session,
        "INTERNAL_ERROR",
        "Turn failed due to timeout",
        expect.anything()
      );
    });
  });

  describe("error", () => {
    it("emits error with message", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "error",
        message: "SDK internal error",
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitError).toHaveBeenCalledWith(
        session,
        "INTERNAL_ERROR",
        "SDK internal error",
        expect.anything()
      );
    });
  });

  describe("unknown event type", () => {
    it("does not emit anything for unknown types", async () => {
      const { handleEvent } = await loadCodexModule();
      const session = createTestSession();
      const options = createTestOptions();

      const event = {
        type: "unknown_event",
      } as TestThreadEvent;

      handleEvent(session, event as never, options as never);

      expect(emitOutput).not.toHaveBeenCalled();
      expect(emitMetadata).not.toHaveBeenCalled();
      expect(emitError).not.toHaveBeenCalled();
      expect(emitHeader).not.toHaveBeenCalled();
    });
  });
});

describe("runTurn", () => {
  it("runTurn is exported as a function", async () => {
    const { runTurn } = await loadCodexModule();
    expect(typeof runTurn).toBe("function");
  });

  it("runTurn accepts session, input, approvalChoice and optional threadId", async () => {
    const { runTurn } = await loadCodexModule();
    const session = createTestSession();

    expect(typeof runTurn).toBe("function");
    expect(session.id).toBe("test-session");
  });
});
