import {AbsoluteFill, Audio, Img, Sequence, staticFile, useCurrentFrame} from 'remotion';
import shotlist from '../shotlist.json';
import {Captions} from './Captions';

type Shot = (typeof shotlist.shots)[number];

/**
 * Remotion addresses the pre-rendered Blender plate by ABSOLUTE frame index,
 * which is why the renderer numbers frames across the whole film.
 */
const Plate: React.FC<{start: number}> = ({start}) => {
  const frame = useCurrentFrame();
  const absolute = start + frame;
  return (
    <AbsoluteFill>
      <Img
        src={staticFile(`frames/frame_${String(absolute).padStart(6, '0')}.png`)}
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />
    </AbsoluteFill>
  );
};

const Grade: React.FC = () => (
  <AbsoluteFill
    style={{
      background:
        'radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 42%, rgba(2,4,8,0.55) 100%)',
      pointerEvents: 'none',
    }}
  />
);

export const Film: React.FC = () => {
  const shots: Shot[] = shotlist.shots as Shot[];
  const twist = shots.find((s) => s.id.startsWith('07')) ?? shots[shots.length - 2];

  return (
    <AbsoluteFill style={{backgroundColor: '#05070c'}}>
      {shots.map((shot) => (
        <Sequence
          key={shot.id}
          from={shot.start}
          durationInFrames={shot.end - shot.start + 1}
          name={shot.id}
        >
          <Plate start={shot.start} />
          <Captions text={shot.text} dur={shot.end - shot.start + 1} />
        </Sequence>
      ))}
      <Grade />

      {/* narration: one file per shot, starting on its own frame */}
      {shots.map((shot) => (
        <Sequence
          key={`a-${shot.id}`}
          from={shot.start}
          durationInFrames={shot.end - shot.start + 1}
          name={`audio-${shot.id}`}
        >
          <Audio src={staticFile(shot.audio)} />
        </Sequence>
      ))}

      {/* foley: a whoosh on every cut, one low impact on the twist */}
      {shots.slice(1).map((shot) => (
        <Sequence
          key={`w-${shot.id}`}
          from={Math.max(shot.start - 4, 0)}
          durationInFrames={14}
          name={`whoosh-${shot.id}`}
        >
          <Audio
            src={staticFile('foley/whoosh.wav')}
            volume={(f) => Math.min(1, f / 4) * 0.2}
          />
        </Sequence>
      ))}
      <Sequence from={twist.start} durationInFrames={30} name="impact">
        <Audio src={staticFile('foley/boom.wav')} volume={0.45} />
      </Sequence>

      {/* room tone, so no cut lands in a hole */}
      <Audio src={staticFile('foley/room.wav')} loop volume={0.05} />
    </AbsoluteFill>
  );
};
