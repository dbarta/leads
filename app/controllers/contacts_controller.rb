class ContactsController < ApplicationController
  before_action :authenticate_user!

  SORTABLE_COLUMNS = %w[last_name title source].freeze

  def index
    @contacts = filtered_contacts
    @contacts = apply_sort(@contacts)
    @pagy, @contacts = pagy(@contacts, limit: 100)
    @total_contacts = Contact.count
  end

  def export
    require "csv"
    contacts = apply_sort(filtered_contacts)
      .includes(company: [:airports, :airport_company_relationships])

    csv_data = CSV.generate(headers: true) do |csv|
      csv << %w[id full_name title email phone linkedin_url source
                company_id company_name company_phone qualification_status airports]
      contacts.each do |c|
        csv << [
          c.id,
          c.full_name,
          c.title,
          c.email,
          c.phone,
          c.linkedin_url,
          c.source,
          c.company_id,
          c.company&.canonical_name,
          c.company&.phone,
          c.company&.qualification_status,
          c.company&.airports&.map(&:faa_code)&.sort&.join("; "),
        ]
      end
    end

    send_data csv_data,
      filename: "contacts_#{Date.today}.csv",
      type: "text/csv",
      disposition: "attachment"
  end

  private

  def filtered_contacts
    scope = Contact.includes(company: [:airports])
    scope = scope.where("contacts.full_name ILIKE ? OR contacts.title ILIKE ? OR contacts.email ILIKE ?",
                        "%#{params[:q]}%", "%#{params[:q]}%", "%#{params[:q]}%") if params[:q].present?
    scope = scope.with_email    if params[:has_email] == "1"
    scope = scope.with_phone    if params[:has_phone] == "1"
    scope = scope.by_source(params[:source])
    if params[:qualification].present?
      scope = scope.joins(:company).where(companies: {qualification_status: params[:qualification]})
    end
    scope
  end

  def apply_sort(scope)
    col = SORTABLE_COLUMNS.include?(params[:sort]) ? params[:sort] : "last_name"
    dir = params[:direction] == "desc" ? "DESC" : "ASC"
    scope.order(Arel.sql("contacts.#{col} #{dir} NULLS LAST"))
  end
end
