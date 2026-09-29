import { loadEnv, defineConfig, Modules } from "@medusajs/framework/utils"

loadEnv(process.env.NODE_ENV || "development", process.cwd())

const redisUrl = process.env.REDIS_URL

module.exports = defineConfig({
  projectConfig: {
    databaseUrl: process.env.DATABASE_URL,
    databaseDriverOptions: { ssl: false, sslmode: "disable" },
    redisUrl,
    http: {
      storeCors: process.env.STORE_CORS!,
      adminCors: process.env.ADMIN_CORS!,
      authCors: process.env.AUTH_CORS!,
      jwtSecret: process.env.JWT_SECRET,
      cookieSecret: process.env.COOKIE_SECRET,
    },
    // Admin diakses lewat HTTP biasa (Tailscale, tanpa TLS). Dengan
    // NODE_ENV=production cookie sesi default-nya Secure dan akan ditolak
    // browser, sehingga login selalu kembali ke halaman sign-in.
    cookieOptions: { secure: false },
  },
  // Event bus, workflow engine, dan locking memakai Redis agar Redis benar-benar
  // menjadi dependensi aplikasi (relevan untuk TC-03 dan TC-04).
  modules: [
    {
      resolve: "@medusajs/medusa/event-bus-redis",
      options: { redisUrl },
    },
    {
      resolve: "@medusajs/medusa/workflow-engine-redis",
      options: { redis: { redisUrl } },
    },
    {
      resolve: "@medusajs/medusa/locking",
      options: {
        providers: [
          {
            resolve: "@medusajs/medusa/locking-redis",
            id: "locking-redis",
            is_default: true,
            options: { redisUrl },
          },
        ],
      },
    },
  ],
})
