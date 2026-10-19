-- =========================================================================
-- Alien Time Listing Studio - Supabase Storage Setup
-- Bucket: 'watch-photos' (Public)
-- =========================================================================

-- 1. Create the public bucket 'watch-photos'
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'watch-photos',
  'watch-photos',
  true,
  52428800, -- 50 MB
  ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/gif']
)
ON CONFLICT (id) DO UPDATE SET
  public = true,
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;

-- 2. Allow public read on public buckets
DROP POLICY IF EXISTS "Allow public read of public buckets" ON storage.buckets;
CREATE POLICY "Allow public read of public buckets"
ON storage.buckets FOR SELECT
TO public
USING (public = true);

-- 3. Storage Object Policies: Allow full public CDN read and uploads to watch-photos
DROP POLICY IF EXISTS "Public can view watch-photos" ON storage.objects;
CREATE POLICY "Public can view watch-photos"
ON storage.objects FOR SELECT
TO public
USING (bucket_id = 'watch-photos');

DROP POLICY IF EXISTS "Allow all on watch-photos" ON storage.objects;
CREATE POLICY "Allow all on watch-photos"
ON storage.objects FOR ALL
TO public
USING (bucket_id = 'watch-photos')
WITH CHECK (bucket_id = 'watch-photos');
