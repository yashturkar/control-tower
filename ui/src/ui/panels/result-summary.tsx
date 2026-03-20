import React from "react";
import { Box, Text } from "ink";
import type { ResultPacket } from "../../types.js";

interface ResultSummaryProps {
  result: ResultPacket | null;
}

function statusColor(status: string): string {
  switch (status) {
    case "success":
      return "green";
    case "partial":
      return "yellow";
    case "blocked":
    case "failed":
      return "red";
    default:
      return "white";
  }
}

export function ResultSummary({ result }: ResultSummaryProps) {
  if (!result) return null;

  const allArtifacts = [
    ...result.artifacts_changed,
    ...result.artifacts_created,
  ];
  const findingsCount = result.findings.length;

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={1}>
      <Box>
        <Text bold>Result: </Text>
        <Text color={statusColor(result.status)} bold>
          {result.status.toUpperCase()}
        </Text>
        <Text> from </Text>
        <Text bold>{result.from_agent}</Text>
      </Box>
      <Text wrap="wrap">{result.summary}</Text>
      {allArtifacts.length > 0 && (
        <Box>
          <Text dimColor>
            Files: {allArtifacts.slice(0, 5).join(", ")}
            {allArtifacts.length > 5 ? ` +${allArtifacts.length - 5} more` : ""}
          </Text>
        </Box>
      )}
      {findingsCount > 0 && (
        <Text color="yellow">
          {findingsCount} finding{findingsCount > 1 ? "s" : ""}
        </Text>
      )}
    </Box>
  );
}
