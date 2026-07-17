module ApplicationHelper
  SAM_ENTITY_STRUCTURES = {
    "2L" => "LLC",
    "2K" => "Corporation",
    "2J" => "Partnership",
    "2S" => "Sole Proprietorship",
    "8H" => "Other",
    "X6" => "U.S. Government Entity",
    "ZZ" => "Other",
  }.freeze

  SAM_BUSINESS_TYPES = {
    "A2" => "Woman-Owned",
    "8W" => "Economically Disadvantaged Woman-Owned",
    "JS" => "Woman-Owned Small Business",
    "23" => "Minority-Owned",
    "OY" => "Black American Owned",
    "HQ" => "Hispanic American Owned",
    "QF" => "Asian Pacific American Owned",
    "A5" => "Veteran-Owned",
    "QE" => "Service-Disabled Veteran-Owned",
    "27" => "Self-Certified Small Disadvantaged",
    "FR" => "Franchise",
    "JV" => "Joint Venture",
    "XS" => "S-Corporation",
  }.freeze

  def sam_entity_structure_label(code)
    SAM_ENTITY_STRUCTURES[code] || code
  end

  def sam_business_type_badges(types_string)
    return [] if types_string.blank?
    types_string.split("~").filter_map { |code| SAM_BUSINESS_TYPES[code.strip] }
  end

  def sort_link_for(label, column, base_path, current_params)
    current_sort = current_params[:sort]
    current_dir  = current_params[:direction]
    if current_sort == column.to_s
      new_dir = current_dir == "asc" ? "desc" : "asc"
      indicator = current_dir == "asc" ? " ▲" : " ▼"
    else
      new_dir   = "asc"
      indicator = ""
    end
    link_to "#{label}#{indicator}",
      base_path + "?" + current_params.to_unsafe_h.except("sort", "direction").merge(sort: column, direction: new_dir).to_query,
      class: "hover:text-blue-600 whitespace-nowrap"
  end
end
