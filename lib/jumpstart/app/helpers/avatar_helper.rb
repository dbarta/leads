module AvatarHelper
  extend self

  def avatar_url_for(record, opts = {})
    size = opts[:size] || 256

    if record.respond_to?(:avatar) && record.avatar.attached? && record.avatar.variable?
      record.avatar.variant(resize_to_fit: [size, size])
    else
      gravatar_url_for(record.email, size: size)
    end
  end

  def ui_avatar_url(**options)
    "https://ui-avatars.com/api/?#{options.to_query}"
  end

  def gravatar_url_for(email, **options)
    hash = Digest::MD5.hexdigest(email&.downcase || "")
    options.reverse_merge!(default: :mp, rating: :pg, size: 64)
    "https://secure.gravatar.com/avatar/#{hash}.png?#{options.to_param}"
  end
end
