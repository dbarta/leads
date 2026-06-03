class Account < ApplicationRecord
  include Billing, Domains, Transfer, Types

  def admins
    account_users.admin.includes(:user).map(&:user)
  end
end
