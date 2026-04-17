# Customizations to the TEI Schema

Customization of the TEI P5 specification is declared in the `riksdagen-motions.odd` file

## Th `correction` element

Add attributes:

- who
- when

## The `correspAction` Element

- Allow empty element.
- type specification
	+ `<rng:value>addedToFile</rng:value>`
	+ `<rng:value>assigned</rng:value>`
	+ `<rng:value>basedOn</rng:value>`
	+ `<rng:value>behandlas_i</rng:value>`
	+ `<rng:value>committee_proposal</rng:value>`
	+ `<rng:value>dismissed</rng:value>`
	+ `<rng:value>dismissal</rng:value>`
	+ `<rng:value>expire</rng:value>`
	+ `<rng:value>expired</rng:value>`
	+ `<rng:value>expires</rng:value>`
	+ `<rng:value>forwarded</rng:value>`
	+ `<rng:value>numbering</rng:value>`
	+ `<rng:value>proposed_referral</rng:value>`
	+ `<rng:value>received</rng:value>`
	+ `<rng:value>reception</rng:value>`
	+ `<rng:value>redirected</rng:value>`
	+ `<rng:value>referred</rng:value>`
	+ `<rng:value>referral</rng:value>`
	+ `<rng:value>registration</rng:value>`
	+ `<rng:value>retracted</rng:value>`
	+ `<rng:value>reviewed</rng:value>`
	+ `<rng:value>reviewing</rng:value>`
	+ `<rng:value>revoked</rng:value>`
	+ `<rng:value>revoking</rng:value>`
	+ `<rng:value>sent</rng:value>`
	+ `<rng:value>signed</rng:value>`
	+ `<rng:value>status</rng:value>`
	+ `<rng:value>submitted</rng:value>`
	+ `<rng:value>submission</rng:value>`
	+ `<rng:value>termination</rng:value>`
	+ `<rng:value>transfer</rng:value>`
	+ `<rng:value>transmitted</rng:value>`

## The `<item>` Element

Added attributes:

- type
- subtype
- who

## The `listPerson` Element

- allow empty element

## The `<p>` Element

Added attributes:

- type
- sybtype


# How to generate the xsd file

Many validation tools rely on an xsd file. It needs to be generated from the odd file. Here's how.

Clone the TEI stylesheets repo:

	 https://github.com/TEIC/Stylesheets.git
	 
Run the `teitoxsd` program

	<path-to-Stylesheets-repo>/bin/teitoxsd --verbose \
		--odd test/data/schema/riksdagen-motions.odd \
		riksdagen-motions.xsd