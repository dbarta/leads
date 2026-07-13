class AddFar139TypeCodeToAirports < ActiveRecord::Migration[8.1]
  def change
    add_column :airports, :far_139_type_code, :string
    add_column :airports, :public_use, :boolean
    add_index :airports, :far_139_type_code
    add_index :airports, :public_use
  end
end
