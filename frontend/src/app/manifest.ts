import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Subframe · Subtitle Studio',
    short_name: 'Subframe',
    description: 'Create, edit and export mobile-first subtitles for short-form video.',
    start_url: '/',
    display: 'standalone',
    background_color: '#08090c',
    theme_color: '#08090c',
    orientation: 'any',
    lang: 'el',
    categories: ['video', 'productivity', 'utilities'],
    icons: [
      {
        src: '/icon.png',
        sizes: '1024x1024',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: '/icon.png',
        sizes: '1024x1024',
        type: 'image/png',
        purpose: 'maskable',
      },
    ],
  };
}
