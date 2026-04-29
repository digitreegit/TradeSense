import React from 'react';

/** “TS” mark — uses currentColor for dark/light sidebar icon backgrounds */
export const TsLogoMark = (props: React.ComponentProps<'svg'>) => (
  <svg {...props} viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden>
    <text x={50} y={72} fontFamily="inherit" fontWeight={700} fontSize={62} fill="currentColor" textAnchor="middle">
      TS
    </text>
  </svg>
);
