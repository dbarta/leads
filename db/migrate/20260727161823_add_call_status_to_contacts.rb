class AddCallStatusToContacts < ActiveRecord::Migration[8.1]
  def change
    add_column :contacts, :call_status, :string
    add_column :contacts, :call_date, :date
  end
end
