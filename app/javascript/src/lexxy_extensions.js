import * as Lexxy from "lexxy"

document.addEventListener("turbo:load", () => Lexxy.highlightCode())
document.addEventListener("turbo:morph", () => Lexxy.highlightCode())

class EmbedsExtension extends Lexxy.Extension {
  get lexicalExtension() {
    return this.defineExtension({ name: "lexxy/embeds_extension" })
  }

  get allowedElements() {
    return [ { tag: "iframe", attributes: [ "loading", "width", "height", "style", "allow", "sandbox", "referrerpolicy" ] } ]
  }
}

Lexxy.configure({
  global: {
    extensions: [EmbedsExtension],
  }
})
