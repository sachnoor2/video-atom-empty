import {loadFont} from '@remotion/fonts';
import {CAPTION_FONT_DATA_URI} from './font';

loadFont({
  family: 'Caption',
  url: CAPTION_FONT_DATA_URI,
  weight: '800',
  format: 'woff2',
});

export const CAPTION_FONT = 'Caption, Inter, Helvetica, Arial, sans-serif';

export const COLORS = {
  bg: '#05070c',
  cyan: '#22d3ee',
  magenta: '#e879f9',
  amber: '#f5b74e',
  bone: '#f2efe9',
};

// Lower third, clear of the platform UI: captions sit above 22% of the frame.
export const CAPTION_BOTTOM = '22%';
