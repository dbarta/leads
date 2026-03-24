module AnnouncementsHelper
  # Use explicit colors so they don't get purged
  ANNOUNCEMENT_COLORS = {
    "new" => "bg-green-100 text-green-800",
    "update" => "bg-blue-100 text-blue-800",
    "improvement" => "bg-purple-100 text-purple-800",
    "fix" => "bg-red-100 text-red-800"
  }

  def announcement_badge(announcement, **options)
    badge announcement.kind.humanize.titleize, **options.merge(color: ANNOUNCEMENT_COLORS.fetch(announcement.kind, "update"))
  end
end
