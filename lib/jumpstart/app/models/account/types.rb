module Account::Types
  extend ActiveSupport::Concern

  included do
    has_prefix_id :acct

    belongs_to :owner, class_name: "User"
    has_many :account_invitations, dependent: :destroy
    has_many :account_users, dependent: :destroy
    has_many :notification_mentions, as: :record, dependent: :destroy, class_name: "Noticed::Event"
    has_many :account_notifications, dependent: :destroy, class_name: "Noticed::Event"
    has_many :users, through: :account_users
    has_many :admins, -> { merge(AccountUser.admin) }, through: :account_users, source: :user

    scope :personal, -> { where(personal: true) }
    scope :team, -> { where(personal: false) }
    scope :sorted, -> { order(personal: :desc, name: :asc) }

    has_one_attached :avatar

    validates :avatar, resizable_image: true
    validates :name, presence: true

    before_create do
      account_users.new(user: owner, admin: true)
    end
  end

  def team?
    !personal?
  end

  def personal_account_for?(user)
    personal? && owner?(user)
  end

  def owner?(user)
    owner_id == user&.id
  end
end
