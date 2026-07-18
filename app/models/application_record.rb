class ApplicationRecord < ActiveRecord::Base
  primary_abstract_class
  self.implicit_order_column = "created_at"

  include ActionView::RecordIdentifier

  # Orders results by column and direction
  def self.sort_by_params(column, direction)
    sortable_column = column.presence_in(sortable_columns) || "created_at"
    order(sortable_column => direction)
  end

  # Converts a search query into a subsequence LIKE pattern.
  # "jkn" → "%j%k%n%" so letters must appear in order anywhere in the string.
  def self.subsequence_pattern(q)
    q.chars.map { |c| sanitize_sql_like(c) }.join("%").then { |p| "%#{p}%" }
  end

  # Returns an array of sortable columns on the model
  # Used with the Sortable controller concern
  #
  # Override this method to add/remove sortable columns
  def self.sortable_columns
    @sortable_columns ||= columns.map(&:name)
  end
end
