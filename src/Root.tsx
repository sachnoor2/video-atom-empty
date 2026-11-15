import {Composition} from 'remotion';
import {Film} from './Film';
import shotlist from '../shotlist.json';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Video"
      component={Film}
      durationInFrames={shotlist.totalFrames}
      fps={shotlist.fps}
      width={shotlist.width}
      height={shotlist.height}
    />
  );
};
