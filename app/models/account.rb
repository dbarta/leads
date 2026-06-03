class Account < ApplicationRecord
  include Billing, Domains, Transfer, Types
end
