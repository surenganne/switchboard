// Report stickers: plays <canvas data-sticker="name"> in ~/.switchboard/report.html.
// Build: bun build stickers/report.ts --minify --format=iife --outfile switchboard/stickers.js
// fun.ts, motions.ts, icons.ts are vendored unchanged from fun-isometric (MIT, Kelvin Adithya, see stickers/LICENSE).
import { brand, play } from './fun'
import { calendar, folder, mailbox, pin, search, toggle, trophy } from './icons'

const ICONS = { calendar, folder, mailbox, pin, search, toggle, trophy }
const palette = brand('#1A3A5C', '#F9C642') // Minfy secondary blue on bodies, accent yellow on coins and checks

document.querySelectorAll<HTMLCanvasElement>('canvas[data-sticker]').forEach((c, i) => {
  const icon = ICONS[c.dataset.sticker as keyof typeof ICONS]
  if (icon) play(c, icon, { palette, enter: 0.1 * i, offset: 20 * i })
})
