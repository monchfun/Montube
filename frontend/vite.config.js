import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
export default defineConfig({base:"./",cacheDir:"../.vite-cache",plugins:[react(),tailwindcss()],resolve:{alias:{"@":path.resolve(import.meta.dirname,"./src")}},server:{proxy:{"/api":"http://127.0.0.1:8080"}},build:{outDir:"../app/static",emptyOutDir:true}});
