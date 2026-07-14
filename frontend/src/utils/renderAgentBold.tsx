import React from 'react';

/** Renders `**segments**` as <strong>; leaves other text plain. */
export function renderLineWithBold(line: string, lineKey: string | number): React.ReactNode {
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      return (
        <strong key={`${lineKey}-b-${i}`} className="agent-md-strong">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <React.Fragment key={`${lineKey}-t-${i}`}>{part}</React.Fragment>;
  });
}
