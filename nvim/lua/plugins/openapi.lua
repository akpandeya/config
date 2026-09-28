-- OpenAPI spec preview: Swagger UI / Redoc in the browser, live-reloaded.
--
--   :SwaggerPreview      open browser preview of the current spec
--   :SwaggerPreviewStop  stop the live-server
--   <leader>os           preview current spec (o = OpenAPI, s = Swagger)
--
-- Works on any yaml/json buffer whose content looks like an OpenAPI spec.
-- Needs `live-server` on PATH (npm i -g live-server).

return {
  "vinnymeller/swagger-preview.nvim",
  cmd = { "SwaggerPreview", "SwaggerPreviewStop" },
  build = "npm install && npm install -g live-server",
  ft = { "yaml", "json" },
  opts = {
    port = 8600,
    host = "localhost",
  },
  init = function()
    local is_openapi = function()
      return vim.fn.search([[^\s*-\?\s*\(openapi\|swagger\)\s*:]], "nw") ~= 0
    end

    vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile" }, {
      group = vim.api.nvim_create_augroup("openapi-preview", { clear = true }),
      pattern = { "*.yaml", "*.yml", "*.json" },
      callback = function(args)
        if is_openapi() then
          vim.keymap.set("n", "<leader>os", "<cmd>SwaggerPreview<CR>", {
            buffer = args.buf,
            desc = "Swagger preview",
          })
        end
      end,
    })
  end,
}
