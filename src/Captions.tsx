import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {CAPTION_BOTTOM, CAPTION_FONT, COLORS} from './theme';

type Chunk = {text: string; from: number; to: number};

/**
 * Kokoro gives no word timings, so the chunk schedule is derived from the
 * scene's measured length, weighted by character count. Chunks never straddle
 * a cut, because every scene is its own Sequence.
 */
export const chunkText = (text: string, dur: number): Chunk[] => {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const groups: string[] = [];
  let i = 0;
  while (i < words.length) {
    const left = words.length - i;
    let take = left >= 3 && words[i].length + words[i + 1].length > 11 ? 3 : 2;
    if (left === 1) take = 1;
    if (words[i].length > 9 && left > 1) take = 1;
    groups.push(words.slice(i, i + take).join(' '));
    i += take;
  }
  const weights = groups.map((g) => g.replace(/\s/g, '').length + 2);
  const total = weights.reduce((a, b) => a + b, 0);
  let acc = 0;
  return groups.map((g, idx) => {
    const from = Math.round((acc / total) * dur);
    acc += weights[idx];
    const to = Math.round((acc / total) * dur);
    return {text: g, from, to: Math.max(to, from + 4)};
  });
};

export const Captions: React.FC<{text: string; dur: number}> = ({text, dur}) => {
  const frame = useCurrentFrame();
  const chunks = chunkText(text, dur);
  const active = chunks.find((c) => frame >= c.from && frame < c.to) ?? chunks[0];
  if (!active) return null;

  const local = frame - active.from;
  const pop = interpolate(local, [0, 4], [0.95, 1], {extrapolateRight: 'clamp'});
  const opacity = interpolate(local, [0, 3], [0, 1], {extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: CAPTION_BOTTOM,
          display: 'flex',
          justifyContent: 'center',
          padding: '0 6%',
        }}
      >
        <div
          style={{
            fontFamily: CAPTION_FONT,
            fontWeight: 800,
            fontSize: 66,
            lineHeight: 1.12,
            letterSpacing: '-0.015em',
            color: COLORS.bone,
            textAlign: 'center',
            maxWidth: '100%',
            padding: '10px 22px 14px',
            borderRadius: 14,
            background: 'rgba(3,6,12,0.34)',
            transform: `scale(${pop})`,
            opacity,
            textShadow:
              '0 4px 16px rgba(0,0,0,0.85), 0 1px 2px rgba(0,0,0,0.9), 0 0 26px rgba(0,0,0,0.5)',
          }}
        >
          {active.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
