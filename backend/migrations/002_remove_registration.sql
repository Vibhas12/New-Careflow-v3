-- Manual patient registration was removed. Registration drafts were its only use of this table.
-- New patients are created only through Data Import (or the seed loader).
DROP TABLE IF EXISTS drafts;
