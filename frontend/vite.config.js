import { defineConfig } from 'vite';

export default defineConfig({
    base: '/',
    publicDir: 'vendor',
    build: {
        outDir: '../web_dist',
        emptyOutDir: true,
    },
});
