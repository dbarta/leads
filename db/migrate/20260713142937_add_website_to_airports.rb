class AddWebsiteToAirports < ActiveRecord::Migration[8.1]
  def change
    add_column :airports, :website, :string
  end
end
