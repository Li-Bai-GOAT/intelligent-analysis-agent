# Cleaning rules

## Missing values

- Preserve missing values by default.
- Drop rows only when an agreed required field is missing and the discarded count is reported.
- Impute only with an explicit method and retain an imputation indicator where practical.

## Duplicates

- An exact duplicate has identical normalized values across every column.
- A business-key duplicate repeats configured identifiers but may contain conflicting values.
- Exact duplicates may be removed when requested. Business-key duplicates require review or a stated winner rule.

## Types

- Read identifiers as strings before conversion.
- Convert configured numeric fields with invalid text becoming missing and reported.
- Convert configured dates with invalid text becoming missing and reported.

## Outliers

For numeric column `x`, compute `IQR = Q3 - Q1`. Values outside `[Q1 - 1.5*IQR, Q3 + 1.5*IQR]` are candidates for review, not automatic deletion.

Sources: pandas missing-data and duplicate guidance, https://pandas.pydata.org/docs/user_guide/ .

