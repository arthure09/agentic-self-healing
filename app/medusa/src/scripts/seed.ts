import { ExecArgs } from "@medusajs/framework/types"
import {
  ContainerRegistrationKeys,
  Modules,
  ProductStatus,
} from "@medusajs/framework/utils"
import {
  addShippingMethodToCartWorkflow,
  completeCartWorkflow,
  createApiKeysWorkflow,
  createCartWorkflow,
  createInventoryLevelsWorkflow,
  createPaymentCollectionForCartWorkflow,
  createPaymentSessionsWorkflow,
  createProductCategoriesWorkflow,
  createProductsWorkflow,
  createRegionsWorkflow,
  createSalesChannelsWorkflow,
  createShippingOptionsWorkflow,
  createShippingProfilesWorkflow,
  createStockLocationsWorkflow,
  createTaxRegionsWorkflow,
  linkSalesChannelsToApiKeyWorkflow,
  linkSalesChannelsToStockLocationWorkflow,
  updateStoresWorkflow,
} from "@medusajs/medusa/core-flows"

// Seed deterministik: PRNG ber-seed tetap agar setiap seed ulang menghasilkan
// katalog dan pesanan yang identik (syarat kondisi awal pengujian yang sama).
const ORDER_COUNT = 120
const CUSTOMER_COUNT = 30
const STOCK_PER_VARIANT = 1000

function mulberry32(seed: number) {
  return () => {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const rand = mulberry32(20260929)
const pick = <T>(xs: T[]) => xs[Math.floor(rand() * xs.length)]
const slug = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")

// [kategori, [nama produk, harga dasar IDR, nilai varian]]
const CATALOG: [string, [string, number, string[]][]][] = [
  ["Pakaian", [
    ["Kaos Katun Basic", 89000, ["S", "M", "L", "XL"]],
    ["Kemeja Batik Pria", 249000, ["M", "L", "XL"]],
    ["Hoodie Polos", 199000, ["M", "L", "XL"]],
    ["Celana Chino", 229000, ["30", "32", "34"]],
    ["Jaket Parasut", 279000, ["M", "L"]],
    ["Kaos Kaki Sport (3 pasang)", 49000, ["Standar"]],
    ["Topi Baseball", 69000, ["Hitam", "Navy"]],
    ["Sarung Tenun", 159000, ["Standar"]],
  ]],
  ["Elektronik", [
    ["Earphone Bluetooth", 299000, ["Hitam", "Putih"]],
    ["Power Bank 10000 mAh", 189000, ["Hitam", "Biru"]],
    ["Kabel USB-C 1 m", 39000, ["Standar"]],
    ["Mouse Nirkabel", 129000, ["Hitam", "Abu-abu"]],
    ["Keyboard Mekanikal", 549000, ["Red Switch", "Brown Switch"]],
    ["Lampu LED Meja", 159000, ["Standar"]],
    ["Speaker Portabel", 349000, ["Hitam", "Merah"]],
    ["Charger 33W", 149000, ["Standar"]],
  ]],
  ["Rumah Tangga", [
    ["Botol Minum 1 L", 59000, ["Hijau", "Biru", "Abu-abu"]],
    ["Set Pisau Dapur", 219000, ["Standar"]],
    ["Wajan Anti Lengket 28 cm", 189000, ["Standar"]],
    ["Handuk Mandi", 79000, ["Putih", "Krem"]],
    ["Sprei Katun Queen", 259000, ["Putih", "Abu-abu"]],
    ["Rak Sepatu 4 Susun", 139000, ["Standar"]],
    ["Keranjang Cucian", 69000, ["Standar"]],
    ["Gelas Kaca (6 pcs)", 89000, ["Standar"]],
  ]],
  ["Makanan & Minuman", [
    ["Kopi Arabika Gayo 250 g", 95000, ["Biji", "Bubuk"]],
    ["Teh Melati 100 g", 35000, ["Standar"]],
    ["Keripik Singkong Pedas", 25000, ["Level 1", "Level 3"]],
    ["Madu Hutan 500 ml", 120000, ["Standar"]],
    ["Sambal Bawang Botol", 32000, ["Original", "Extra Pedas"]],
    ["Granola 400 g", 75000, ["Standar"]],
    ["Cokelat Batang 100 g", 29000, ["Susu", "Hitam"]],
    ["Gula Aren Cair 250 ml", 38000, ["Standar"]],
  ]],
  ["Olahraga", [
    ["Matras Yoga 6 mm", 179000, ["Ungu", "Hitam"]],
    ["Dumbel 2 kg (sepasang)", 159000, ["Standar"]],
    ["Tali Skipping", 45000, ["Standar"]],
    ["Bola Futsal", 189000, ["Standar"]],
    ["Raket Badminton", 329000, ["Standar"]],
    ["Sepatu Lari", 499000, ["40", "41", "42", "43"]],
    ["Tas Olahraga", 229000, ["Hitam", "Navy"]],
    ["Botol Shaker", 49000, ["Standar"]],
  ]],
]

const FIRST = ["Andi", "Budi", "Citra", "Dewi", "Eko", "Fitri", "Gilang", "Hana", "Indra", "Joko",
  "Kartika", "Lestari", "Made", "Nur", "Oki", "Putri", "Rizki", "Sari", "Tono", "Wulan"]
const LAST = ["Pratama", "Saputra", "Wijaya", "Santoso", "Hidayat", "Lestari", "Nugroho", "Kusuma", "Siregar", "Rahman"]
const CITIES: [string, string, string][] = [
  ["Surabaya", "Jawa Timur", "60111"], ["Jakarta Selatan", "DKI Jakarta", "12190"],
  ["Bandung", "Jawa Barat", "40115"], ["Yogyakarta", "DI Yogyakarta", "55281"],
  ["Semarang", "Jawa Tengah", "50132"], ["Denpasar", "Bali", "80234"],
  ["Medan", "Sumatera Utara", "20112"], ["Makassar", "Sulawesi Selatan", "90111"],
]

export default async function seed({ container }: ExecArgs) {
  const logger = container.resolve(ContainerRegistrationKeys.LOGGER)
  const link = container.resolve(ContainerRegistrationKeys.LINK)
  const query = container.resolve(ContainerRegistrationKeys.QUERY)
  const fulfillmentService = container.resolve(Modules.FULFILLMENT)
  const salesChannelService = container.resolve(Modules.SALES_CHANNEL)
  const storeService = container.resolve(Modules.STORE)

  const { data: existing } = await query.graph({
    entity: "product",
    fields: ["id"],
    pagination: { take: 1 },
  })
  if (existing.length > 0) {
    logger.info("[seed] Data sudah ada, seed dilewati.")
    return
  }

  logger.info("[seed] Store, sales channel, dan API key...")
  const [store] = await storeService.listStores()
  let [salesChannel] = await salesChannelService.listSalesChannels({
    name: "Default Sales Channel",
  })
  if (!salesChannel) {
    const { result } = await createSalesChannelsWorkflow(container).run({
      input: { salesChannelsData: [{ name: "Default Sales Channel" }] },
    })
    salesChannel = result[0]
  }
  await updateStoresWorkflow(container).run({
    input: {
      selector: { id: store.id },
      update: {
        name: "Toko Agentic",
        supported_currencies: [{ currency_code: "idr", is_default: true }],
        default_sales_channel_id: salesChannel.id,
      },
    },
  })
  const {
    result: [publishableKey],
  } = await createApiKeysWorkflow(container).run({
    input: {
      api_keys: [{ title: "Storefront", type: "publishable", created_by: "" }],
    },
  })
  await linkSalesChannelsToApiKeyWorkflow(container).run({
    input: { id: publishableKey.id, add: [salesChannel.id] },
  })

  logger.info("[seed] Region dan pajak Indonesia...")
  const {
    result: [region],
  } = await createRegionsWorkflow(container).run({
    input: {
      regions: [{
        name: "Indonesia",
        currency_code: "idr",
        countries: ["id"],
        payment_providers: ["pp_system_default"],
      }],
    },
  })
  await createTaxRegionsWorkflow(container).run({
    input: [{ country_code: "id", provider_id: "tp_system" }],
  })

  logger.info("[seed] Gudang dan pengiriman...")
  const {
    result: [location],
  } = await createStockLocationsWorkflow(container).run({
    input: {
      locations: [{
        name: "Gudang Surabaya",
        address: { city: "Surabaya", country_code: "ID", address_1: "Jl. Raya ITS" },
      }],
    },
  })
  await updateStoresWorkflow(container).run({
    input: { selector: { id: store.id }, update: { default_location_id: location.id } },
  })
  await link.create({
    [Modules.STOCK_LOCATION]: { stock_location_id: location.id },
    [Modules.FULFILLMENT]: { fulfillment_provider_id: "manual_manual" },
  })

  let [shippingProfile] = await fulfillmentService.listShippingProfiles({ type: "default" })
  if (!shippingProfile) {
    const { result } = await createShippingProfilesWorkflow(container).run({
      input: { data: [{ name: "Default Shipping Profile", type: "default" }] },
    })
    shippingProfile = result[0]
  }

  const fulfillmentSet = await fulfillmentService.createFulfillmentSets({
    name: "Pengiriman Gudang Surabaya",
    type: "shipping",
    service_zones: [{
      name: "Indonesia",
      geo_zones: [{ country_code: "id", type: "country" }],
    }],
  })
  await link.create({
    [Modules.STOCK_LOCATION]: { stock_location_id: location.id },
    [Modules.FULFILLMENT]: { fulfillment_set_id: fulfillmentSet.id },
  })

  const shippingRules = [
    { attribute: "enabled_in_store", value: "true", operator: "eq" as const },
    { attribute: "is_return", value: "false", operator: "eq" as const },
  ]
  const { result: shippingOptions } = await createShippingOptionsWorkflow(container).run({
    input: [
      ["Reguler", "Tiba 3-5 hari", "reguler", 15000],
      ["Ekspres", "Tiba 1-2 hari", "ekspres", 35000],
    ].map(([label, description, code, amount]) => ({
      name: label as string,
      price_type: "flat" as const,
      provider_id: "manual_manual",
      service_zone_id: fulfillmentSet.service_zones[0].id,
      shipping_profile_id: shippingProfile.id,
      type: { label: label as string, description: description as string, code: code as string },
      prices: [
        { currency_code: "idr", amount: amount as number },
        { region_id: region.id, amount: amount as number },
      ],
      rules: shippingRules,
    })),
  })
  await linkSalesChannelsToStockLocationWorkflow(container).run({
    input: { id: location.id, add: [salesChannel.id] },
  })

  logger.info("[seed] Kategori dan produk...")
  const { result: categories } = await createProductCategoriesWorkflow(container).run({
    input: {
      product_categories: CATALOG.map(([name]) => ({ name, is_active: true })),
    },
  })
  const categoryId = Object.fromEntries(categories.map((c) => [c.name, c.id]))

  const { result: products } = await createProductsWorkflow(container).run({
    input: {
      products: CATALOG.flatMap(([category, items]) =>
        items.map(([title, price, values]) => ({
          title,
          handle: slug(title),
          status: ProductStatus.PUBLISHED,
          category_ids: [categoryId[category]],
          shipping_profile_id: shippingProfile.id,
          options: [{ title: "Varian", values }],
          variants: values.map((v, i) => ({
            title: v,
            sku: `${slug(title)}-${slug(v)}`.toUpperCase(),
            options: { Varian: v },
            manage_inventory: true,
            // Varian ukuran lebih besar sedikit lebih mahal agar harga bervariasi
            prices: [{ currency_code: "idr", amount: price + i * 5000 }],
          })),
          sales_channels: [{ id: salesChannel.id }],
        }))
      ),
    },
  })

  logger.info("[seed] Stok inventaris...")
  const { data: inventoryItems } = await query.graph({
    entity: "inventory_item",
    fields: ["id"],
  })
  await createInventoryLevelsWorkflow(container).run({
    input: {
      inventory_levels: inventoryItems.map((item) => ({
        location_id: location.id,
        inventory_item_id: item.id,
        stocked_quantity: STOCK_PER_VARIANT,
      })),
    },
  })

  logger.info(`[seed] ${ORDER_COUNT} pesanan dari ${CUSTOMER_COUNT} pelanggan...`)
  const variants = products.flatMap((p) => p.variants.map((v) => v.id))
  const customers = Array.from({ length: CUSTOMER_COUNT }, (_, i) => {
    const first = FIRST[i % FIRST.length]
    const last = LAST[(i * 7) % LAST.length]
    const [city, province, postal] = CITIES[i % CITIES.length]
    return {
      email: `${slug(first)}.${slug(last)}${i}@contoh.id`,
      address: {
        first_name: first,
        last_name: last,
        address_1: `Jl. Contoh No. ${i + 1}`,
        city,
        province,
        postal_code: postal,
        country_code: "id",
        phone: `08123${String(100000 + i).slice(1)}`,
      },
    }
  })

  for (let n = 0; n < ORDER_COUNT; n++) {
    const customer = pick(customers)
    const lineCount = 1 + Math.floor(rand() * 4)
    const items = Array.from({ length: lineCount }, () => ({
      variant_id: pick(variants),
      quantity: 1 + Math.floor(rand() * 3),
    }))
    const { result: cart } = await createCartWorkflow(container).run({
      input: {
        region_id: region.id,
        sales_channel_id: salesChannel.id,
        email: customer.email,
        currency_code: "idr",
        shipping_address: customer.address,
        billing_address: customer.address,
        items,
      },
    })
    await addShippingMethodToCartWorkflow(container).run({
      input: { cart_id: cart.id, options: [{ id: pick(shippingOptions).id }] },
    })
    const { result: paymentCollection } = await createPaymentCollectionForCartWorkflow(
      container
    ).run({ input: { cart_id: cart.id } })
    await createPaymentSessionsWorkflow(container).run({
      input: {
        payment_collection_id: (paymentCollection as { id: string }).id,
        provider_id: "pp_system_default",
      },
    })
    await completeCartWorkflow(container).run({ input: { id: cart.id } })
    if ((n + 1) % 20 === 0) logger.info(`[seed]   ${n + 1}/${ORDER_COUNT} pesanan`)
  }

  logger.info(
    `[seed] Selesai: ${products.length} produk, ${variants.length} varian, ${ORDER_COUNT} pesanan.`
  )
}
