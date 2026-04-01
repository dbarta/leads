import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = {
    publicKey: String,
    clientSecret: String,
  }

  async connect() {
    this.stripe = Stripe(this.publicKeyValue)
    this.checkout = await this.stripe.createEmbeddedCheckoutPage({fetchClientSecret: this.fetchClientSecret.bind(this)})
    this.checkout.mount(this.element)
  }

  disconnect() {
    this.checkout.destroy()
  }

  fetchClientSecret() {
    return Promise.resolve(this.clientSecretValue)
  }
}
