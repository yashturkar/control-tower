import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
import type { BootStep } from "../types.js";

interface BootScreenProps {
  steps: BootStep[];
  error: string | null;
}

function StepIcon({ state }: { state: BootStep["state"] }) {
  switch (state) {
    case "pending":
      return <Text dimColor>  </Text>;
    case "running":
      return (
        <Text color="cyan">
          <Spinner type="dots" />
        </Text>
      );
    case "done":
      return <Text color="green">✓ </Text>;
    case "error":
      return <Text color="red">✗ </Text>;
  }
}

export function BootScreen({ steps, error }: BootScreenProps) {
  return (
    <Box flexDirection="column" paddingX={2} paddingY={1}>
      <Box justifyContent="center" marginBottom={1}>
        <Text bold color="cyan">
          ▄▄▄ CONTROL TOWER ▄▄▄
        </Text>
      </Box>

      <Box marginBottom={1}>
        <Text color="cyan">
          <Spinner type="dots" />
        </Text>
        <Text bold> Tower is towering...</Text>
      </Box>

      {steps.map((step) => (
        <Box key={step.name}>
          <StepIcon state={step.state} />
          <Text
            dimColor={step.state === "pending"}
            color={step.state === "error" ? "red" : undefined}
          >
            {step.label}
          </Text>
          {step.error && (
            <Text color="red"> — {step.error}</Text>
          )}
        </Box>
      ))}

      {error && (
        <Box marginTop={1}>
          <Text color="red" bold>
            Boot failed: {error}
          </Text>
        </Box>
      )}
    </Box>
  );
}
