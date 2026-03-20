import React from "react";
import { Text } from "ink";
import type { MemoryStatus } from "../../types.js";

interface MemoryIndicatorProps {
  status: MemoryStatus;
}

export function MemoryIndicator({ status }: MemoryIndicatorProps) {
  switch (status.state) {
    case "idle":
      return <Text dimColor>◉ Memory: idle</Text>;
    case "reading":
      return (
        <Text color="blue">
          ◉ Memory: {status.detail || "reading..."}
        </Text>
      );
    case "storing":
      return (
        <Text color="yellow" bold>
          ◉ Memory: {status.detail || "STORING"}
        </Text>
      );
    case "syncing":
      return (
        <Text color="magenta" bold>
          ◉ Memory: {status.detail || "syncing"}
        </Text>
      );
  }
}
