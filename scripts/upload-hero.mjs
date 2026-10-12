// Uploads the gallery's hero video to R2 and records it in src/data/gallery.json.
//
//   npm run hero -- "gallery-source/ON DECK/videos/IMG_6403.MOV"
//
// The clip is repackaged as a web-friendly .mp4 that starts playing before it has
// fully downloaded, and a still frame is saved to show while it loads.

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import ffmpeg from 'ffmpeg-static'
import sharp from 'sharp'

const MANIFEST = 'src/data/gallery.json'

const env = (k) => {
  const v = process.env[k]
  if (!v) throw new Error(`Missing ${k} in .env.local`)
  return v
}

const input = process.argv[2]
if (!input || !existsSync(input)) {
  console.error('Usage: npm run hero -- "path/to/clip.MOV"')
  process.exit(1)
}

const BUCKET = env('R2_BUCKET')
const PUBLIC_URL = env('R2_PUBLIC_URL').replace(/\/$/, '')
const s3 = new S3Client({
  region: 'auto',
  endpoint: `https://${env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com`,
  credentials: { accessKeyId: env('R2_ACCESS_KEY_ID'), secretAccessKey: env('R2_SECRET_ACCESS_KEY') },
})

const tmp = mkdtempSync(join(tmpdir(), 'soc-hero-'))

try {
  const mp4 = join(tmp, 'hero.mp4')
  const frame = join(tmp, 'frame.jpg')

  // Keep the video and audio as-is (already H.264/AAC), drop camera metadata tracks,
  // and move the index to the front so playback can start right away.
  // If a future clip isn't H.264 (e.g. iPhone HEVC), swap "-c copy" for a re-encode.
  execFileSync(ffmpeg, ['-y', '-i', input, '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy', '-movflags', '+faststart', mp4], { stdio: 'ignore' })
  execFileSync(ffmpeg, ['-y', '-ss', '0.5', '-i', mp4, '-frames:v', '1', '-q:v', '2', frame], { stdio: 'ignore' })

  const video = readFileSync(mp4)
  const hash = createHash('sha1').update(video).digest('hex').slice(0, 10)
  const poster = await sharp(frame).webp({ quality: 80 }).toBuffer({ resolveWithObject: true })

  const put = (Key, Body, ContentType) =>
    s3.send(new PutObjectCommand({ Bucket: BUCKET, Key, Body, ContentType, CacheControl: 'public, max-age=31536000, immutable' }))

  const videoKey = `gallery/hero-${hash}.mp4`
  const posterKey = `gallery/hero-${hash}-poster.webp`
  await put(videoKey, video, 'video/mp4')
  await put(posterKey, poster.data, 'image/webp')

  const manifest = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : { parties: {} }
  manifest.hero = {
    video: `${PUBLIC_URL}/${videoKey}`,
    poster: `${PUBLIC_URL}/${posterKey}`,
    width: poster.info.width,
    height: poster.info.height,
  }
  writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + '\n')

  console.log(`Uploaded hero video (${(video.length / 1e6).toFixed(1)} MB) and poster`)
  console.log(manifest.hero.video)
} finally {
  rmSync(tmp, { recursive: true, force: true })
}
