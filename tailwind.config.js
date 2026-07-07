/** Tailwind build for Django templates — utilities generated from template scan. */
module.exports = {
  content: ["./templates/**/*.html", "./apps/**/views/*.py", "./apps/**/*_views.py"],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        edify: {
          primary: "#2e505f",
          teal: "#0ea5a4",
          deep: "#0f2a33",
        },
      },
      fontFamily: { sans: ["Outfit", "ui-sans-serif", "system-ui", "sans-serif"] },
    },
  },
};
