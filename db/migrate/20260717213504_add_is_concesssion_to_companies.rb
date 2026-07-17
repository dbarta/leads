class AddIsConcesssionToCompanies < ActiveRecord::Migration[8.1]
  def change
    add_column :companies, :is_concession, :boolean, default: false, null: false
  end
end
