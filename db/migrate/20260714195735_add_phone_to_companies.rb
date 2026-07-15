class AddPhoneToCompanies < ActiveRecord::Migration[8.1]
  def change
    add_column :companies, :phone, :string
  end
end
