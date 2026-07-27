class AddPhoneVerificationToContacts < ActiveRecord::Migration[8.1]
  def change
    add_column :contacts, :phone_verified, :boolean
    add_column :contacts, :phone_registered_name, :string
  end
end
