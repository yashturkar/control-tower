import React, { useState, useCallback } from "react";
import { Box, Text, useInput } from "ink";

interface InputBarProps {
  isRunning: boolean;
  onSubmit: (text: string) => void;
}

export function InputBar({ isRunning, onSubmit }: InputBarProps) {
  const [value, setValue] = useState("");

  useInput(
    useCallback(
      (input: string, key: { return?: boolean; backspace?: boolean; delete?: boolean }) => {
        if (isRunning) return;

        if (key.return && value.trim()) {
          onSubmit(value.trim());
          setValue("");
          return;
        }

        if (key.backspace || key.delete) {
          setValue((prev) => prev.slice(0, -1));
          return;
        }

        if (input && !key.return) {
          setValue((prev) => prev + input);
        }
      },
      [isRunning, value, onSubmit],
    ),
  );

  if (isRunning) {
    return (
      <Box width="100%">
        <Text dimColor>  Tower is thinking...</Text>
      </Box>
    );
  }

  return (
    <Box width="100%">
      <Text color="green" bold>{"> "}</Text>
      <Text>{value}</Text>
      <Text color="gray">█</Text>
    </Box>
  );
}
