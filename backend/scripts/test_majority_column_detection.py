from layout_table_reconstructor_majority import reconstruct_table

def item(i,text,left,right,top):
    return {"item_id":f"I{i}","text":text,"page_number":1,"reading_order":i,"label":"text","hierarchy_level":3,"bbox":{"left":left,"right":right,"top":top,"bottom":top-8}}

def page65():
    xs=[228,292,342,407,465,509]
    out=[item(i+1,"£'000",x,x+24,500) for i,x in enumerate(xs)]
    vals=[("156,944",218,253),("75,859",286,316),("232,803",331,366),("147,538",399,428),("80,340",460,485),("227,878",500,529)]
    out += [item(20+i,t,l,r,480) for i,(t,l,r) in enumerate(vals)]
    out += [item(40,"Revenue",108,145,490)]
    return out

def page89():
    xs=[200,243,287,328,374,420,464,508]
    out=[item(i+1,"£'000",x,x+20,500) for i,x in enumerate(xs)]
    vals=[("7,682",200,224),("1,534",242,266),("32",298,309),("9,248",327,352),("7,615",374,394),("2,807",420,440),("77",475,484),("10,499",503,528)]
    out += [item(20+i,t,l,r,480) for i,(t,l,r) in enumerate(vals)]
    out += [item(40,"Receivables",125,168,490)]
    return out

for name,items,expected in [("page65",page65(),6),("page89",page89(),8)]:
    result=reconstruct_table(items)
    assert result["column_count"]==expected,(name,result["column_count"],result["columns"])
    assert result["column_detection"]["method"]=="unit_majority_confirmed_by_body"
    print(name,result["column_count"],result["column_detection"])
