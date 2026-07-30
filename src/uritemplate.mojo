"""RFC 6570 URI-template expansion over caller-owned UTF-8 buffers."""

from std.sys.info import simd_width_of

comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]


struct Writer:
    var dst_addr: Int
    var capacity: Int
    var position: Int

    def __init__(out self, dst_addr: Int, capacity: Int):
        self.dst_addr = dst_addr
        self.capacity = capacity
        self.position = 0

    def byte(mut self, value: UInt8):
        if self.position < self.capacity:
            var dst = BPtr(unsafe_from_address=self.dst_addr)
            dst[self.position] = value
        self.position += 1

    def literal(mut self, value: StringSlice):
        var data = value.as_bytes()
        for i in range(len(data)):
            self.byte(data[i])

    def source(mut self, src: BPtr, start: Int, end: Int):
        comptime W = simd_width_of[DType.float64]()
        var size = end - start
        var writable = min(size, max(0, self.capacity - self.position))
        var i = 0
        if writable > 0:
            var dst = BPtr(unsafe_from_address=self.dst_addr)
            while i + W <= writable:
                var values = src.load[width=W](start + i)
                dst.store(self.position + i, values)
                i += W
            while i < writable:
                dst[self.position + i] = src[start + i]
                i += 1
        self.position += size


def read_u32(src: BPtr, position: Int) -> Int:
    return (
        Int(src[position])
        | (Int(src[position + 1]) << 8)
        | (Int(src[position + 2]) << 16)
        | (Int(src[position + 3]) << 24)
    )


def valid_wire(wire: BPtr, wire_len: Int) -> Bool:
    """Validate every nested length before the renderer follows the wire data."""
    if wire_len < 4:
        return False
    var entries = read_u32(wire, 0)
    var pos = 4
    for _ in range(entries):
        if pos > wire_len - 4:
            return False
        var key_len = read_u32(wire, pos)
        pos += 4
        if key_len > wire_len - pos:
            return False
        pos += key_len
        if pos >= wire_len:
            return False
        var kind = Int(wire[pos])
        pos += 1
        if kind == 0:
            continue
        if kind == 1 or (kind >= 4 and kind <= 7):
            if pos > wire_len - 4:
                return False
            var size = read_u32(wire, pos)
            pos += 4
            if size > wire_len - pos:
                return False
            pos += size
            continue
        if kind != 2 and kind != 3:
            return False
        if pos > wire_len - 4:
            return False
        var count = read_u32(wire, pos)
        pos += 4
        for _ in range(count):
            if kind == 3:
                if pos > wire_len - 4:
                    return False
                var item_key_len = read_u32(wire, pos)
                pos += 4
                if item_key_len > wire_len - pos:
                    return False
                pos += item_key_len
            if pos >= wire_len:
                return False
            var is_none = Int(wire[pos])
            pos += 1
            if is_none != 0 and is_none != 1:
                return False
            if is_none == 0:
                if pos > wire_len - 4:
                    return False
                var item_len = read_u32(wire, pos)
                pos += 4
                if item_len > wire_len - pos:
                    return False
                pos += item_len
    return pos == wire_len


def equal_slice(
    first: BPtr,
    first_start: Int,
    first_end: Int,
    second: BPtr,
    second_start: Int,
    second_end: Int,
) -> Bool:
    if first_end - first_start != second_end - second_start:
        return False
    for i in range(first_end - first_start):
        if first[first_start + i] != second[second_start + i]:
            return False
    return True


def skip_wire_value(wire: BPtr, position: Int, kind: Int) -> Int:
    var pos = position
    if kind == 0:
        return pos
    if kind == 1 or kind >= 4:
        return pos + 4 + read_u32(wire, pos)
    var count = read_u32(wire, pos)
    pos += 4
    if kind == 2:
        for _ in range(count):
            var is_none = Int(wire[pos])
            pos += 1
            if is_none == 0:
                pos += 4 + read_u32(wire, pos)
        return pos
    for _ in range(count):
        pos += 4 + read_u32(wire, pos)
        var is_none = Int(wire[pos])
        pos += 1
        if is_none == 0:
            pos += 4 + read_u32(wire, pos)
    return pos


def find_value(
    wire: BPtr,
    wire_len: Int,
    name_src: BPtr,
    name_start: Int,
    name_end: Int,
) -> Tuple[Int, Int, Int]:
    if wire_len < 4:
        return (-1, 0, 0)
    var entries = read_u32(wire, 0)
    var pos = 4
    for _ in range(entries):
        if pos + 5 > wire_len:
            return (-1, 0, 0)
        var key_len = read_u32(wire, pos)
        pos += 4
        var key_start = pos
        pos += key_len
        if pos >= wire_len:
            return (-1, 0, 0)
        var kind = Int(wire[pos])
        pos += 1
        var matched = equal_slice(
            wire, key_start, key_start + key_len,
            name_src, name_start, name_end
        )
        if kind == 0:
            if matched:
                return (0, 0, 0)
        elif kind == 1 or kind >= 4:
            if pos + 4 > wire_len:
                return (-1, 0, 0)
            var size = read_u32(wire, pos)
            if matched:
                return (kind, pos + 4, size)
        else:
            if pos + 4 > wire_len:
                return (-1, 0, 0)
            var count = read_u32(wire, pos)
            if matched:
                return (kind, pos + 4, count)
        pos = skip_wire_value(wire, pos, kind)
        if pos > wire_len:
            return (-1, 0, 0)
    return (-1, 0, 0)


def hex_digit(value: Int) -> UInt8:
    return UInt8(value + 48 if value < 10 else value + 55)


def is_hex(value: UInt8) -> Bool:
    return (
        (value >= UInt8(48) and value <= UInt8(57))
        or (value >= UInt8(65) and value <= UInt8(70))
        or (value >= UInt8(97) and value <= UInt8(102))
    )


def has_percent_escape(src: BPtr, start: Int, end: Int) -> Bool:
    var i = start
    while i + 2 < end:
        if (
            src[i] == UInt8(37)
            and is_hex(src[i + 1])
            and is_hex(src[i + 2])
        ):
            return True
        i += 1
    return False


def is_unreserved(value: UInt8) -> Bool:
    return (
        (value >= UInt8(48) and value <= UInt8(57))
        or (value >= UInt8(65) and value <= UInt8(90))
        or (value >= UInt8(97) and value <= UInt8(122))
        or value == UInt8(126)
        or value == UInt8(45)
        or value == UInt8(95)
        or value == UInt8(46)
    )


def is_reserved(value: UInt8) -> Bool:
    return (
        value == UInt8(58) or value == UInt8(47) or value == UInt8(63)
        or value == UInt8(35) or value == UInt8(91) or value == UInt8(93)
        or value == UInt8(64) or value == UInt8(33) or value == UInt8(36)
        or value == UInt8(38) or value == UInt8(39) or value == UInt8(40)
        or value == UInt8(41) or value == UInt8(42) or value == UInt8(43)
        or value == UInt8(44) or value == UInt8(59) or value == UInt8(61)
    )


def quoted(
    mut writer: Writer,
    src: BPtr,
    start: Int,
    end: Int,
    quote_mode: Int,
):
    if quote_mode != 0 and has_percent_escape(src, start, end):
        writer.source(src, start, end)
        return
    comptime W = simd_width_of[DType.float64]()
    var i = start
    while i + W <= end:
        var values = src.load[width=W](i)
        var safe = (
            (values.ge(UInt8(48)) & values.le(UInt8(57)))
            | (values.ge(UInt8(65)) & values.le(UInt8(90)))
            | (values.ge(UInt8(97)) & values.le(UInt8(122)))
            | values.eq(UInt8(126))
            | values.eq(UInt8(45))
            | values.eq(UInt8(95))
            | values.eq(UInt8(46))
        )
        if quote_mode != 0:
            safe |= (
                values.eq(UInt8(58)) | values.eq(UInt8(47))
                | values.eq(UInt8(63)) | values.eq(UInt8(35))
                | values.eq(UInt8(91)) | values.eq(UInt8(93))
                | values.eq(UInt8(64)) | values.eq(UInt8(33))
                | values.eq(UInt8(36)) | values.eq(UInt8(38))
                | values.eq(UInt8(39)) | values.eq(UInt8(40))
                | values.eq(UInt8(41)) | values.eq(UInt8(42))
                | values.eq(UInt8(43)) | values.eq(UInt8(44))
                | values.eq(UInt8(59)) | values.eq(UInt8(61))
            )
        if safe.reduce_and():
            writer.source(src, i, i + W)
        else:
            for lane in range(W):
                var value = values[lane]
                if safe[lane]:
                    writer.byte(value)
                else:
                    writer.byte(UInt8(37))
                    writer.byte(hex_digit(Int(value) >> 4))
                    writer.byte(hex_digit(Int(value) & 15))
        i += W
    while i < end:
        var value = src[i]
        var safe = is_unreserved(value)
        if quote_mode != 0 and is_reserved(value):
            safe = True
        if safe:
            writer.byte(value)
        else:
            writer.byte(UInt8(37))
            writer.byte(hex_digit(Int(value) >> 4))
            writer.byte(hex_digit(Int(value) & 15))
        i += 1


def quoted_none(mut writer: Writer):
    writer.literal("None")


def operator_kind(value: UInt8) -> Int:
    if value == UInt8(43):
        return 1
    if value == UInt8(35):
        return 2
    if value == UInt8(46):
        return 3
    if value == UInt8(47):
        return 4
    if value == UInt8(59):
        return 5
    if value == UInt8(63):
        return 6
    if value == UInt8(38):
        return 7
    if (
        value == UInt8(61) or value == UInt8(44) or value == UInt8(33)
        or value == UInt8(64) or value == UInt8(124)
    ):
        return 8
    return 0


def quote_mode(operator: Int) -> Int:
    if operator == 1:
        return 1
    if operator == 2:
        return 2
    return 0


def separator(operator: Int) -> UInt8:
    if operator == 3:
        return UInt8(46)
    if operator == 4:
        return UInt8(47)
    if operator == 5:
        return UInt8(59)
    if operator == 6 or operator == 7:
        return UInt8(38)
    return UInt8(44)


def write_prefix(mut writer: Writer, operator: Int, original: UInt8):
    if operator == 2:
        writer.byte(UInt8(35))
    elif operator >= 3 and operator <= 7:
        writer.byte(original)
    elif operator == 8:
        writer.byte(original)


def sequence_has_value(
    wire: BPtr, position: Int, count: Int, kind: Int
) -> Bool:
    var pos = position
    if kind == 2:
        for _ in range(count):
            var is_none = Int(wire[pos])
            pos += 1
            if is_none == 0:
                return True
            if is_none == 0:
                pos += 4 + read_u32(wire, pos)
        return False
    for _ in range(count):
        pos += 4 + read_u32(wire, pos)
        var is_none = Int(wire[pos])
        pos += 1
        if is_none == 0:
            return True
        if is_none == 0:
            pos += 4 + read_u32(wire, pos)
    return False


def will_expand(
    wire: BPtr,
    kind: Int,
    position: Int,
    count: Int,
    operator: Int,
    explode: Bool,
) -> Bool:
    if kind < 1:
        return False
    if operator == 6 or operator == 7:
        return kind == 1 or kind >= 4 or count > 0
    if operator == 3 or operator == 4:
        if kind == 1 or kind >= 4:
            return True
        return count > 0 and sequence_has_value(wire, position, count, kind)
    if operator == 5 and kind == 2 and explode:
        return count > 0 and sequence_has_value(wire, position, count, kind)
    return True


def utf8_prefix_end(
    src: BPtr, start: Int, end: Int, prefix: Int
) -> Int:
    if prefix == 0:
        return end
    var characters = 0
    for i in range(start, end):
        if (src[i] & UInt8(0xC0)) != UInt8(0x80):
            characters += 1
    var wanted = prefix
    if wanted < 0:
        wanted = max(0, characters + wanted)
    if wanted >= characters:
        return end
    var seen = 0
    var pos = start
    while pos < end:
        if (src[pos] & UInt8(0xC0)) != UInt8(0x80):
            if seen == wanted:
                return pos
            seen += 1
        pos += 1
    return end


def parse_prefix(
    src: BPtr, start: Int, end: Int
) -> Int:
    if start >= end:
        return 0
    var sign = 1
    var pos = start
    if src[pos] == UInt8(45):
        sign = -1
        pos += 1
    var value = 0
    while pos < end:
        value = value * 10 + Int(src[pos] - UInt8(48))
        pos += 1
    return sign * value


def write_scalar(
    mut writer: Writer,
    wire: BPtr,
    position: Int,
    size: Int,
    operator: Int,
    name_src: BPtr,
    name_start: Int,
    name_end: Int,
    prefix: Int,
    truthy: Bool,
    byte_prefix: Bool,
):
    var value_end = position + size
    if byte_prefix and prefix > 0:
        value_end = min(value_end, position + prefix)
    elif byte_prefix and prefix < 0:
        value_end = max(position, value_end + prefix)
    else:
        value_end = utf8_prefix_end(wire, position, value_end, prefix)
    var has_output = truthy and value_end > position
    if operator == 6 or operator == 7:
        writer.source(name_src, name_start, name_end)
        writer.byte(UInt8(61))
        if has_output:
            quoted(writer, wire, position, value_end, 0)
    elif operator == 5:
        writer.source(name_src, name_start, name_end)
        if has_output:
            writer.byte(UInt8(61))
            quoted(writer, wire, position, value_end, 0)
    else:
        quoted(writer, wire, position, value_end, quote_mode(operator))


def write_list(
    mut writer: Writer,
    wire: BPtr,
    position: Int,
    count: Int,
    operator: Int,
    explode: Bool,
    name_src: BPtr,
    name_start: Int,
    name_end: Int,
):
    var pos = position
    var emitted = 0
    if (operator == 6 or operator == 7) and not explode:
        writer.source(name_src, name_start, name_end)
        writer.byte(UInt8(61))
    elif operator == 5 and not explode:
        writer.source(name_src, name_start, name_end)
        writer.byte(UInt8(61))
    for _ in range(count):
        var is_none = Int(wire[pos])
        pos += 1
        var item_start = pos
        var item_len = 0
        if is_none == 0:
            item_len = read_u32(wire, pos)
            item_start = pos + 4
            pos = item_start + item_len
        var skip_none = (
            (operator == 3 or operator == 4)
            or (operator == 5 and explode)
        ) and is_none != 0
        if skip_none:
            continue
        if emitted > 0:
            if explode and (
                operator == 3 or operator == 4 or operator == 5
                or operator == 6 or operator == 7
            ):
                writer.byte(separator(operator))
            else:
                writer.byte(UInt8(44))
        if explode and (operator == 5 or operator == 6 or operator == 7):
            writer.source(name_src, name_start, name_end)
            writer.byte(UInt8(61))
        if is_none != 0:
            quoted_none(writer)
        else:
            quoted(
                writer, wire, item_start, item_start + item_len,
                0 if operator >= 3 and operator <= 7 else quote_mode(operator)
            )
        emitted += 1


def write_map(
    mut writer: Writer,
    wire: BPtr,
    position: Int,
    count: Int,
    operator: Int,
    explode: Bool,
    name_src: BPtr,
    name_start: Int,
    name_end: Int,
):
    var pos = position
    var emitted = 0
    if (operator == 6 or operator == 7 or operator == 5) and not explode:
        writer.source(name_src, name_start, name_end)
        writer.byte(UInt8(61))
    for _ in range(count):
        var key_len = read_u32(wire, pos)
        var key_start = pos + 4
        pos = key_start + key_len
        var is_none = Int(wire[pos])
        pos += 1
        var value_start = pos
        var value_len = 0
        if is_none == 0:
            value_len = read_u32(wire, pos)
            value_start = pos + 4
            pos = value_start + value_len
        if (
            is_none != 0
            and (operator == 3 or operator == 4 or operator == 5)
        ):
            continue
        if emitted > 0:
            if explode and operator >= 3 and operator <= 7:
                writer.byte(separator(operator))
            else:
                writer.byte(UInt8(44))
        quoted(
            writer, wire, key_start, key_start + key_len,
            0 if operator >= 3 and operator <= 7 else quote_mode(operator)
        )
        writer.byte(UInt8(61) if explode else UInt8(44))
        if is_none != 0:
            quoted_none(writer)
        else:
            quoted(
                writer, wire, value_start, value_start + value_len,
                0 if operator >= 3 and operator <= 7 else quote_mode(operator)
            )
        emitted += 1


def expand_expression(
    mut writer: Writer,
    template: BPtr,
    expr_start: Int,
    expr_end: Int,
    wire: BPtr,
    wire_len: Int,
) -> Bool:
    var operator = operator_kind(template[expr_start])
    var operator_char = template[expr_start]
    var pos = expr_start + (1 if operator != 0 else 0)
    var emitted = 0
    while pos <= expr_end:
        var var_end = pos
        while var_end < expr_end and template[var_end] != UInt8(44):
            var_end += 1
        var spec_end = var_end
        var default_start = -1
        for i in range(pos, var_end):
            if template[i] == UInt8(61):
                spec_end = i
                default_start = i + 1
                break
        var explode = False
        while spec_end > pos and template[spec_end - 1] == UInt8(42):
            explode = True
            spec_end -= 1
        var name_end = spec_end
        var prefix = 0
        for i in range(pos, spec_end):
            if template[i] == UInt8(58):
                name_end = i
                prefix = parse_prefix(template, i + 1, spec_end)
                break
        var found = find_value(wire, wire_len, template, pos, name_end)
        var kind = found[0]
        var value_position = found[1]
        var value_count = found[2]
        var using_default = False
        if (
            (
                kind <= 0 or kind == 4 or kind == 6
                or ((kind == 2 or kind == 3) and value_count == 0)
            )
            and default_start >= 0 and default_start < var_end
        ):
            kind = 1
            value_position = default_start
            value_count = var_end - default_start
            using_default = True
        if will_expand(
            wire,
            kind, value_position, value_count, operator, explode
        ):
            if emitted == 0:
                write_prefix(writer, operator, operator_char)
            else:
                writer.byte(separator(operator))
            var value_src = wire
            if using_default:
                value_src = template
            if kind == 1 or kind >= 4:
                write_scalar(
                    writer, value_src, value_position, value_count, operator,
                    template, pos, name_end, prefix,
                    kind != 4 and kind != 6 and kind != 7,
                    kind == 5 or kind == 6
                )
            elif kind == 2:
                write_list(
                    writer, wire, value_position, value_count, operator, explode,
                    template, pos, name_end
                )
            elif kind == 3:
                write_map(
                    writer, wire, value_position, value_count, operator, explode,
                    template, pos, name_end
                )
            emitted += 1
        pos = var_end + 1
        if var_end == expr_end:
            break
    return emitted > 0


def render(
    mut writer: Writer,
    template: BPtr,
    template_len: Int,
    wire: BPtr,
    wire_len: Int,
    partial: Bool,
):
    var pos = 0
    while pos < template_len:
        if template[pos] != UInt8(123):
            writer.byte(template[pos])
            pos += 1
            continue
        var close = pos + 1
        while close < template_len and template[close] != UInt8(125):
            close += 1
        if close >= template_len or close == pos + 1:
            writer.byte(template[pos])
            pos += 1
            continue
        var before = writer.position
        _ = expand_expression(
            writer, template, pos + 1, close, wire, wire_len
        )
        if partial and writer.position == before:
            writer.position = before
            writer.source(template, pos, close + 1)
        pos = close + 1


@export("mut_expand")
def mut_expand(
    template_addr: Int,
    template_len: Int,
    wire_addr: Int,
    wire_len: Int,
    dst_addr: Int,
    capacity: Int,
    partial: Int,
) abi("C") -> Int:
    if (
        template_addr <= 0 or wire_addr <= 0 or dst_addr <= 0
        or template_len < 0 or wire_len < 4 or capacity <= 0
    ):
        return -1
    var template = BPtr(unsafe_from_address=template_addr)
    var wire = BPtr(unsafe_from_address=wire_addr)
    if not valid_wire(wire, wire_len):
        return -2
    var writer = Writer(dst_addr, capacity)
    render(
        writer, template, template_len, wire, wire_len, partial != 0
    )
    return writer.position
