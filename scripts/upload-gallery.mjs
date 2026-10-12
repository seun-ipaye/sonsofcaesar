// Turns the original photos in gallery-source/ into web-sized copies, uploads them
// to Cloudflare R2, and writes src/data/gallery.json for the gallery page.
//
//   npm run gallery                 -> every party folder
//   npm run gallery -- "ON DECK"    -> just that party
//
// Photos already uploaded are skipped. Photos deleted from gallery-source/ are
// removed from R2 and from the gallery. Videos are handled separately.

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { extname, join } from 'node:path'
import { DeleteObjectsCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import sharp from 'sharp'

const SOURCE = 'gallery-source'
const MANIFEST = 'src/data/gallery.json'
const SIZES = { thumb: 800, full: 2000 } // longest side, in pixels
const QUALITY = { thumb: 72, full: 82 }
const CONCURRENCY = 4
const PHOTO_EXTS = ['.jpg', '.jpeg', '.png', '.heic']

const env = (k) => {
  const v = process.env[k]
  if (!v) throw new Error(`Missing ${k} in .env.local`)
  return v
}

const BUCKET = env('R2_BUCKET')
const PUBLIC_URL = env('R2_PUBLIC_URL').replace(/\/$/, '')
const s3 = new S3Client({
  region: 'auto',
  endpoint: `https://${env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com`,
  credentials: { accessKeyId: env('R2_ACCESS_KEY_ID'), secretAccessKey: env('R2_SECRET_ACCESS_KEY') },
})

// "ON DECK" -> "on-deck"
const slugify = (name) => name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

const manifest = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : { parties: {} }

const onlyParty = process.argv[2]
const partyFolders = readdirSync(SOURCE, { withFileTypes: true })
  .filter((d) => d.isDirectory() && (!onlyParty || d.name === onlyParty))
  .map((d) => d.name)

if (onlyParty && partyFolders.length === 0) {
  console.error(`No folder called "${onlyParty}" in ${SOURCE}/`)
  process.exit(1)
}

const tmp = mkdtempSync(join(tmpdir(), 'soc-gallery-'))

// sharp can't read HEIC, so convert those to JPEG with macOS's sips first
function readablePath(file) {
  if (extname(file).toLowerCase() !== '.heic') return file
  const out = join(tmp, createHash('md5').update(file).digest('hex') + '.jpg')
  execFileSync('sips', ['-s', 'format', 'jpeg', file, '--out', out], { stdio: 'ignore' })
  return out
}

async function upload(key, body) {
  await s3.send(
    new PutObjectCommand({
      Bucket: BUCKET,
      Key: key,
      Body: body,
      ContentType: 'image/webp',
      // Keys include a content hash, so a file at a given URL never changes
      CacheControl: 'public, max-age=31536000, immutable',
    }),
  )
}

async function processPhoto(party, folder, name) {
  const file = join(SOURCE, folder, name)
  const original = readFileSync(file)
  const hash = createHash('sha1').update(original).digest('hex').slice(0, 10)
  const base = `gallery/${party}/${slugify(name.replace(/\.[^.]+$/, ''))}-${hash}`

  // .rotate() applies the camera's orientation so portrait shots aren't sideways
  const img = sharp(readablePath(file)).rotate()
  const [thumb, full, stats] = await Promise.all([
    img.clone().resize(SIZES.thumb, SIZES.thumb, { fit: 'inside' }).webp({ quality: QUALITY.thumb }).toBuffer({ resolveWithObject: true }),
    img.clone().resize(SIZES.full, SIZES.full, { fit: 'inside', withoutEnlargement: true }).webp({ quality: QUALITY.full }).toBuffer(),
    img.clone().stats(),
  ])

  await upload(`${base}-thumb.webp`, thumb.data)
  await upload(`${base}-full.webp`, full)

  const { r, g, b } = stats.dominant
  return {
    source: name,
    hash,
    width: thumb.info.width,
    height: thumb.info.height,
    // Shown as a placeholder while the thumbnail loads
    color: `rgb(${r}, ${g}, ${b})`,
    thumb: `${PUBLIC_URL}/${base}-thumb.webp`,
    full: `${PUBLIC_URL}/${base}-full.webp`,
  }
}

// Runs fn over items, a few at a time
async function pool(items, fn) {
  const results = []
  let next = 0
  await Promise.all(
    Array.from({ length: CONCURRENCY }, async () => {
      while (next < items.length) {
        const i = next++
        results[i] = await fn(items[i], i)
      }
    }),
  )
  return results
}

const keyOf = (url) => url.slice(PUBLIC_URL.length + 1)

try {
  for (const folder of partyFolders) {
    const party = slugify(folder)
    const previous = manifest.parties[party]?.photos ?? []
    const bySource = new Map(previous.map((p) => [p.source, p]))

    const names = readdirSync(join(SOURCE, folder))
      .filter((n) => PHOTO_EXTS.includes(extname(n).toLowerCase()))
      .sort()

    console.log(`\n${folder} (${party}): ${names.length} photos`)

    let uploaded = 0
    const photos = await pool(names, async (name) => {
      const existing = bySource.get(name)
      const size = statSync(join(SOURCE, folder, name)).size
      // Skip photos that haven't changed since the last upload
      if (existing && existing.bytes === size) return existing
      const photo = { ...(await processPhoto(party, folder, name)), bytes: size }
      uploaded++
      process.stdout.write(`  uploaded ${uploaded}: ${name}\n`)
      return photo
    })

    // Remove photos that were deleted (or replaced) from R2
    const keep = new Set(photos.map((p) => p.thumb))
    const stale = previous.filter((p) => !keep.has(p.thumb))
    if (stale.length) {
      await s3.send(
        new DeleteObjectsCommand({
          Bucket: BUCKET,
          Delete: { Objects: stale.flatMap((p) => [{ Key: keyOf(p.thumb) }, { Key: keyOf(p.full) }]) },
        }),
      )
    }

    manifest.parties[party] = { folder, photos }
    console.log(`  ${uploaded} uploaded, ${names.length - uploaded} unchanged, ${stale.length} removed`)
  }

  writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + '\n')
  console.log(`\nWrote ${MANIFEST}`)
} finally {
  rmSync(tmp, { recursive: true, force: true })
}
