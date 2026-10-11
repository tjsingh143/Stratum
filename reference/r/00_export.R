# Export each reference dataset to CSV (into the un-vendored cache) and record
# its structure, so the data dictionary is generated from the files, not the brief.
source("r/common.R")
dir.create(DERIVED, showWarnings = FALSE, recursive = TRUE)

data(Oxide, package = "MEMSS")
data(Semi2, package = "SASmixed")
data(Semiconductor, package = "SASmixed")

furnace <- read_dat("_fetched/nist/FURNACE.DAT", c("run", "zone", "wafer", "thickness"))
litho <- read_dat("_fetched/nist/LITHOGRA.DAT",
                  c("cassette", "wafer", "site", "width_raw", "run_seq", "width_cleaned"))
oxide <- as.data.frame(Oxide)
semi <- as.data.frame(Semiconductor)
semi$Grp <- as.character(semi$Grp)  # ordered factor "1/1".."4/3" kept as its label

write.csv(furnace, file.path(DERIVED, "furnace.csv"), row.names = FALSE)
write.csv(litho, file.path(DERIVED, "lithography.csv"), row.names = FALSE)
write.csv(oxide, file.path(DERIVED, "oxide.csv"), row.names = FALSE)
write.csv(semi, file.path(DERIVED, "semiconductor.csv"), row.names = FALSE)

# Counts of observations in every cell of a cross-classification, as a set.
cell_counts <- function(d, cols) sort(unique(as.vector(table(d[cols]))))
levels_of <- function(x) sort(unique(as.character(x)))
n_missing <- function(d) sum(!complete.cases(d))

structure <- list(
  furnace = list(
    rows = nrow(furnace), columns = names(furnace), incomplete_rows = n_missing(furnace),
    runs = levels_of(furnace$run), zones = levels_of(furnace$zone), wafers = levels_of(furnace$wafer),
    obs_per_run_zone = cell_counts(furnace, c("run", "zone")),
    obs_per_run_zone_wafer = cell_counts(furnace, c("run", "zone", "wafer")),
    thickness_range = range(furnace$thickness),
    thickness_all_integer = all(furnace$thickness == round(furnace$thickness))
  ),
  lithography = list(
    rows = nrow(litho), columns = names(litho), incomplete_rows = n_missing(litho),
    cassettes = length(unique(litho$cassette)), wafers = levels_of(litho$wafer),
    sites = levels_of(litho$site),
    obs_per_cassette_wafer = cell_counts(litho, c("cassette", "wafer")),
    obs_per_cassette_wafer_site = cell_counts(litho, c("cassette", "wafer", "site")),
    run_seq_is_row_order = all(litho$run_seq == seq_len(nrow(litho))),
    raw_minus_cleaned_range = range(litho$width_raw - litho$width_cleaned)
  ),
  oxide = list(
    rows = nrow(oxide), columns = names(oxide), incomplete_rows = n_missing(oxide),
    column_classes = vapply(oxide, function(x) class(x)[1], ""),
    sources = levels_of(oxide$Source), lots = levels_of(oxide$Lot),
    wafer_labels = levels_of(oxide$Wafer), sites = levels_of(oxide$Site),
    obs_per_lot_wafer = cell_counts(oxide, c("Lot", "Wafer")),
    obs_per_lot_wafer_site = cell_counts(oxide, c("Lot", "Wafer", "Site")),
    sources_per_lot = sort(unique(tapply(oxide$Source, oxide$Lot, function(s) length(unique(s))))),
    lots_by_source = lapply(split(as.character(oxide$Lot), oxide$Source), levels_of),
    identical_to_SASmixed_Semi2 = isTRUE(all.equal(
      oxide[do.call(order, oxide[c("Lot", "Wafer", "Site")]), ],
      as.data.frame(Semi2)[do.call(order, as.data.frame(Semi2)[c("Lot", "Wafer", "Site")]), ],
      check.attributes = FALSE)),
    identical_to_nlme_Oxide = isTRUE(all.equal(
      oxide[do.call(order, oxide[c("Lot", "Wafer", "Site")]), ],
      as.data.frame(nlme::Oxide)[do.call(order, as.data.frame(nlme::Oxide)[c("Lot", "Wafer", "Site")]), ],
      check.attributes = FALSE)),
    thickness_range = range(oxide$Thickness)
  ),
  semiconductor = list(
    rows = nrow(semi), columns = names(semi), incomplete_rows = n_missing(semi),
    column_classes = vapply(Semiconductor, function(x) class(x)[1], ""),
    et_levels = levels_of(semi$ET), wafer_labels = levels_of(semi$Wafer),
    positions = levels_of(semi$position), grp_levels = length(unique(semi$Grp)),
    wafers_per_et = cell_counts(unique(semi[c("ET", "Wafer")]), "ET"),
    obs_per_grp_position = cell_counts(semi, c("Grp", "position")),
    grp_equals_et_slash_wafer = identical(semi$Grp, paste(semi$ET, semi$Wafer, sep = "/")),
    resistance_range = range(semi$resistance)
  )
)
str(structure, max.level = 2, vec.len = 10)
write_result(structure, "structure.json")
