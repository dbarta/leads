require "net/http"

class ActionText::Embed < ApplicationRecord
  include ActionText::Attachable

  # Implements a matching PermitScrubber to Rails that allows scripts from trusted sources
  # https://github.com/rails/rails-html-sanitizer/blob/main/lib/rails/html/sanitizer.rb#L156-L167
  class Scrubber < Rails::HTML::PermitScrubber
    def initialize(...)
      super
      self.tags = ActionText::ContentHelper.allowed_tags + %w[figure figcaption iframe blockquote time]
      self.attributes = ActionText::ContentHelper.allowed_attributes + %w[data-id data-flickr-embed target allow frameborder referrerpolicy allowfullscreen loading]
    end

    def scrub(node)
      if node.name == "script" && ActionText::Embed.allowed_script?(node)
        STOP
      else
        super
      end
    end
  end

  # Allowed script src URLs for OEmbeds
  ALLOWED_SCRIPTS = [
    /^\/\/s.imgur.com/,
    /^https:\/\/platform.twitter.com/,
    /^https:\/\/embed.bsky.app/
  ]

  # Allowed OEmbed providers
  PROVIDERS = {
    bluesky: {
      endpoint: "https://embed.bsky.app/oembed",
      urls: [
        /^https:\/\/bsky\.app\/profile\/.*\/post\/.*/
      ]
    },
    bunny_stream: {
      endpoint: "https://video.bunnycdn.com/OEmbed",
      urls: [
        /^https:\/\/player\.mediadelivery\.net\/play\/.*/
      ]
    },
    imgur: {
      endpoint: "https://api.imgur.com/oembed",
      urls: [
        /https?:\/\/(.+\.)?imgur\.com\/.*/
      ]
    },
    reddit: {
      endpoint: "https://www.reddit.com/oembed",
      urls: [
        /^https?:\/\/(www\.)?reddit\.com\/r\/[^\/]+\/comments\/.*/
      ]
    },
    soundcloud: {
      endpoint: "https://soundcloud.com/oembed",
      urls: [
        /^https?:\/\/(www\.)?soundcloud\.com\/.*/
      ]
    },
    spotify: {
      endpoint: "https://open.spotify.com/oembed",
      urls: [
        /^https?:\/\/(open|play)\.spotify\.com\/.*/
      ]
    },
    vimeo: {
      endpoint: "https://vimeo.com/api/oembed",
      urls: [
        /^https?:\/\/(.+\.)?vimeo\.com/
      ]
    },
    x: {
      endpoint: "https://publish.twitter.com/oembed",
      urls: [
        /^https?:\/\/(www\.)?twitter\.com\/(.*?)\/status(es)?\/.*/,
        /^https?:\/\/(www\.)?x\.com\/(.*?)\/status(es)?\/.*/
      ]
    },
    youtube: {
      endpoint: "https://www.youtube.com/oembed",
      urls: [
        /^https?:\/\/((m|www)\.)?youtube\.com\/watch.*/,
        /^https?:\/\/((m|www)\.)?youtube\.com\/playlist.*/,
        /^https?:\/\/((m|www)\.)?youtube\.com\/shorts.*/,
        /^https?:\/\/((m|www)\.)?youtube\.com\/live.*/,
        /^https?:\/\/([^.]+\.)?youtu\.be\/(.*?)/
      ]
    }
  }.freeze

  # Returns an ActionText::Embed for a given URL
  def self.from_url(url) = find_by(url: url) || from_oembed(url)

  # Creates an ActionText::Embed from a URL
  def self.from_oembed(url)
    if (endpoint = endpoint_for(url))
      uri = URI.parse(endpoint).tap { it.query = {url: url}.to_query }
      response = JSON.parse Net::HTTP.get(uri)
      create(url: url, fields: response)
    end
  rescue JSON::ParserError
  end

  # Returns OEmbed endpoint for URL
  def self.endpoint_for(url) = provider_for(url)&.dig(:endpoint)

  def self.provider_for(url)
    PROVIDERS.values.find do |conf|
      conf.dig(:urls).any? { it.match?(url) }
    end
  end

  # Returns boolean if embed's script tags are allowed
  def self.allowed_script?(node)
    (src = node.attr("src")) && ALLOWED_SCRIPTS.any? { |pattern| pattern.match?(src) }
  end

  def self.delegate_fields(*keys)
    keys.each do |key|
      define_method(key) { fields[key.to_s] }
    end
  end

  delegate_fields :type, :version, :title, :author_name, :author_url, :provider_name, :provider_url, :thumbnail_url, :thumbnail_width, :thumbnail_height, :height, :width, :html

  %w[link photo rich video].each do |embed_type|
    define_method :"#{embed_type}?" do
      type == embed_type
    end
  end

  def attachable_plain_text_representation(caption = nil) = "[#{caption || url}]"

  def content_type = "application/vnd.actiontext.embed"
end
