// Configure your import map in config/importmap.rb. Read more: https://github.com/rails/importmap-rails
import "@hotwired/turbo-rails"
import "channels"
import "controllers"
import "src"

// Load after src so extensions work
import { highlightCode } from "lexxy"
import "@rails/actiontext"
document.addEventListener("turbo:load", () => highlightCode())
document.addEventListener("turbo:morph", () => highlightCode())

import LocalTime from "local-time"
LocalTime.start()
document.addEventListener("turbo:morph", () => LocalTime.run())
