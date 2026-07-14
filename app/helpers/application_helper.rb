module ApplicationHelper
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
