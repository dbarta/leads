// Configure your import map in config/importmap.rb. Read more: https://github.com/rails/importmap-rails
import "@hotwired/turbo-rails"
import "@rails/actiontext"
import "channels"
import "controllers"
import "src"

import LocalTime from "local-time"
LocalTime.start()
document.addEventListener("turbo:morph", () => LocalTime.run())
