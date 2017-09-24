dot=$(wildcard *.dot)
pngs=$(patsubst %.dot,%.png,$(dot))

$(pngs): $(dot)
	dot -Tpng -o $@ $< 

