class AddRunIdToContacts < ActiveRecord::Migration[8.1]
  def change
    add_reference :contacts, :run, null: true, foreign_key: true
  end
end
