import {loadFont} from '@remotion/google-fonts/Inter';

// One face, loaded through Remotion's font loader so the first frame waits for it.
const {fontFamily} = loadFont('normal', {weights: ['800'], subsets: ['latin']});

export const CAPTION_FONT = `${fontFamily}, Inter, Helvetica, Arial, sans-serif`;

export const COLORS = {
  bg: '#05070c',
  cyan: '#22d3ee',
  magenta: '#e879f9',
  amber: '#f5b74e',
  bone: '#f2efe9',
};

// Lower third, clear of the platform UI: captions sit above 22% of the frame.
export const CAPTION_BOTTOM = '22%';
